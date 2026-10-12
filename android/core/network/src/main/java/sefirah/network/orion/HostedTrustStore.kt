package sefirah.network.orion

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.system.Os
import android.system.OsConstants
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import java.io.File
import java.io.FileOutputStream
import java.security.MessageDigest
import java.util.UUID

data class HostedCheckpoint(val version: Long, val digest: String)
data class HostedTrustSnapshot(val checkpoint: HostedCheckpoint, val signedAnchor: JsonObject?, val usedDeviceIds: Set<String>)
data class HostedInboxReceipt(val id: String, val duplicate: Boolean)

/** Public identity/high-water state and already-encrypted inbox only. */
interface HostedTrustStore {
    fun bind(binding: JsonObject)
    fun checkpoint(): HostedCheckpoint
    fun snapshot(): HostedTrustSnapshot
    fun advance(expected: HostedTrustSnapshot, next: HostedTrustSnapshot)
    fun acceptIncoming(envelope: JsonObject, expected: HostedCheckpoint, now: Long): HostedInboxReceipt
    fun pendingIncoming(now: Long): List<JsonObject>
    fun completeIncoming(id: String) { throw HostedSessionException() }
}

/** Android SQLite backend. No payload, private key or account token is stored. */
class AndroidHostedTrustStore private constructor(private val database: File, private var allowInitialBinding: Boolean = false) : HostedTrustStore {
    private var binding: String? = null

    companion object {
        private val lock = Any()
        private const val MARKER = "ORION_HOSTED_TRUST_V1\n"

        private fun folder(context: Context, deployment: String, device: String): File {
            check(UUID.fromString(deployment).toString() == deployment && Regex("dev_[a-f0-9]{32}").matches(device))
            return File(File(File(context.applicationContext.noBackupFilesDir.canonicalFile, "orion-hosted-trust-v1"), deployment), device)
        }

        fun create(context: Context, deployment: String, device: String): AndroidHostedTrustStore = guarded {
            synchronized(lock) {
                val folder = folder(context, deployment, device)
                check(folder.mkdirs() || folder.isDirectory)
                check(folder.canonicalFile == folder.absoluteFile)
                Os.chmod(folder.absolutePath, 448) // 0700
                val marker = File(folder, "created.marker")
                val database = File(folder, "trust.sqlite3")
                check(!database.exists() && marker.createNewFile())
                Os.chmod(marker.absolutePath, 384) // 0600
                FileOutputStream(marker).use { it.write(MARKER.toByteArray(Charsets.US_ASCII)); it.fd.sync() }
                SQLiteDatabase.openOrCreateDatabase(database, null).use { db ->
                    Os.chmod(database.absolutePath, 384)
                    db.execSQL("PRAGMA journal_mode=WAL")
                    db.execSQL("CREATE TABLE identity(id INTEGER PRIMARY KEY CHECK(id=1),binding TEXT NOT NULL,version INTEGER NOT NULL,digest TEXT NOT NULL,signed_anchor TEXT)")
                    db.execSQL("CREATE TABLE used_devices(id TEXT PRIMARY KEY)")
                    db.execSQL("CREATE TABLE incoming(id TEXT PRIMARY KEY,header TEXT NOT NULL,ciphertext TEXT NOT NULL,digest TEXT NOT NULL,expires_at INTEGER NOT NULL)")
                }
                val directory = Os.open(folder.absolutePath, OsConstants.O_RDONLY, 0)
                try { Os.fsync(directory) } finally { Os.close(directory) }
                AndroidHostedTrustStore(database, allowInitialBinding = true)
            }
        }

        fun openExisting(context: Context, deployment: String, device: String): AndroidHostedTrustStore = guarded {
            val folder = folder(context, deployment, device)
            val marker = File(folder, "created.marker")
            val database = File(folder, "trust.sqlite3")
            check(folder.canonicalFile == folder.absoluteFile && marker.canonicalFile == marker.absoluteFile &&
                database.canonicalFile == database.absoluteFile && database.isFile && database.length() > 0 && marker.length() == MARKER.length.toLong())
            check(marker.readText(Charsets.US_ASCII) == MARKER)
            AndroidHostedTrustStore(database)
        }

        private inline fun <T> guarded(action: () -> T): T = try { action() } catch (_: Exception) { throw HostedSessionException() }
    }

    private fun <T> transaction(action: (SQLiteDatabase) -> T): T = guarded {
        synchronized(lock) {
            check(database.isFile && database.canonicalFile == database.absoluteFile)
            SQLiteDatabase.openDatabase(database.absolutePath, null, SQLiteDatabase.OPEN_READWRITE).use { db ->
                db.execSQL("PRAGMA synchronous=FULL")
                db.execSQL("CREATE TABLE IF NOT EXISTS completed_incoming(id TEXT PRIMARY KEY)")
                db.beginTransaction()
                try {
                    val result = action(db)
                    db.setTransactionSuccessful()
                    result
                } finally { db.endTransaction() }
            }
        }
    }

    private fun row(db: SQLiteDatabase): Pair<String, HostedCheckpoint>? =
        db.rawQuery("SELECT binding,version,digest FROM identity WHERE id=1", null).use {
            if (it.moveToFirst()) it.getString(0) to HostedCheckpoint(it.getLong(1), it.getString(2)) else null
        }

    private fun bound(db: SQLiteDatabase): HostedCheckpoint {
        val row = row(db) ?: throw HostedSessionException()
        check(binding != null && row.first == binding)
        return row.second
    }

    override fun bind(binding: JsonObject) = transaction { db ->
        // Existing checkpoints retain their high-water mark. A missing anchor
        // cannot be invented by migration: acceptChain must verify its history.
        val columns = db.rawQuery("PRAGMA table_info(identity)", null).use { cursor ->
            buildSet { while (cursor.moveToNext()) add(cursor.getString(1)) }
        }
        if ("signed_anchor" !in columns) db.execSQL("ALTER TABLE identity ADD COLUMN signed_anchor TEXT")
        db.execSQL("CREATE TABLE IF NOT EXISTS used_devices(id TEXT PRIMARY KEY)")
        val wire = String(HostedEnvelope.canonical(binding), Charsets.US_ASCII)
        val old = row(db)
        if (old == null) {
            check(allowInitialBinding)
            db.execSQL("INSERT INTO identity(id,binding,version,digest) VALUES(1,?,0,'')", arrayOf(wire))
        } else check(old.first == wire)
        this.binding = wire
        allowInitialBinding = false
    }

    override fun checkpoint(): HostedCheckpoint = transaction { bound(it) }

    private fun snapshot(db: SQLiteDatabase): HostedTrustSnapshot {
        val checkpoint = bound(db)
        val anchor = db.rawQuery("SELECT signed_anchor FROM identity WHERE id=1", null).use {
            check(it.moveToFirst())
            if (it.isNull(0)) null else Json.parseToJsonElement(it.getString(0)).jsonObject
        }
        val used = db.rawQuery("SELECT id FROM used_devices ORDER BY id", null).use {
            buildSet { while (it.moveToNext()) add(it.getString(0)) }
        }
        return HostedTrustSnapshot(checkpoint, anchor, used)
    }

    override fun snapshot(): HostedTrustSnapshot = transaction { snapshot(it) }

    override fun advance(expected: HostedTrustSnapshot, next: HostedTrustSnapshot) = transaction { db ->
        check(snapshot(db) == expected && next.checkpoint.version >= expected.checkpoint.version)
        check(next.usedDeviceIds.containsAll(expected.usedDeviceIds))
        val anchor = next.signedAnchor ?: throw HostedSessionException()
        val roster = anchor.getValue("roster").jsonObject
        check(roster.getValue("version").jsonPrimitive.long == next.checkpoint.version &&
            HostedSession.digest(HostedEnvelope.canonical(roster)) == next.checkpoint.digest)
        if (expected.checkpoint.version == next.checkpoint.version) check(expected.checkpoint == next.checkpoint)
        db.execSQL("UPDATE identity SET version=?,digest=?,signed_anchor=? WHERE id=1", arrayOf<Any>(next.checkpoint.version,
            next.checkpoint.digest, String(HostedEnvelope.canonical(anchor), Charsets.US_ASCII)))
        for (id in next.usedDeviceIds - expected.usedDeviceIds) db.execSQL("INSERT INTO used_devices VALUES(?)", arrayOf(id))
    }

    override fun acceptIncoming(envelope: JsonObject, expected: HostedCheckpoint, now: Long): HostedInboxReceipt = transaction { db ->
        check(bound(db) == expected)
        db.execSQL("DELETE FROM incoming WHERE expires_at<=?", arrayOf(now - 86_400))
        val header = envelope.getValue("header").jsonObject
        check(header.getValue("expires_at").jsonPrimitive.content.toLong() > now)
        val id = header.getValue("id").jsonPrimitive.content
        val digest = MessageDigest.getInstance("SHA-256").digest(HostedEnvelope.canonical(envelope)).joinToString("") { "%02x".format(it) }
        val existing = db.rawQuery("SELECT digest FROM incoming WHERE id=?", arrayOf(id)).use { if (it.moveToFirst()) it.getString(0) else null }
        if (existing != null) {
            check(existing == digest)
            HostedInboxReceipt(id, duplicate = true)
        } else {
            check(db.rawQuery("SELECT COUNT(*) FROM incoming WHERE expires_at>? AND id NOT IN (SELECT id FROM completed_incoming)", arrayOf(now.toString())).use { it.moveToFirst(); it.getInt(0) } < 1000)
            db.execSQL("INSERT INTO incoming VALUES(?,?,?,?,?)", arrayOf<Any>(id,
                String(HostedEnvelope.canonical(header), Charsets.US_ASCII),
                envelope.getValue("ciphertext").jsonPrimitive.content, digest,
                header.getValue("expires_at").jsonPrimitive.content.toLong()))
            HostedInboxReceipt(id, duplicate = false)
        }
    }

    override fun pendingIncoming(now: Long): List<JsonObject> = transaction { db ->
        bound(db)
        db.execSQL("DELETE FROM incoming WHERE expires_at<=?", arrayOf(now - 86_400))
        db.execSQL("DELETE FROM completed_incoming WHERE id NOT IN (SELECT id FROM incoming)")
        db.rawQuery("SELECT header,ciphertext FROM incoming WHERE expires_at>? AND id NOT IN (SELECT id FROM completed_incoming) ORDER BY rowid LIMIT 1000", arrayOf(now.toString())).use { cursor ->
            buildList {
                while (cursor.moveToNext()) add(JsonObject(mapOf("header" to Json.parseToJsonElement(cursor.getString(0)),
                    "ciphertext" to kotlinx.serialization.json.JsonPrimitive(cursor.getString(1)))))
            }
        }
    }
    override fun completeIncoming(id: String) = transaction { db ->
        bound(db)
        check(UUID.fromString(id).toString() == id)
        db.execSQL("INSERT OR IGNORE INTO completed_incoming(id) VALUES(?)", arrayOf(id))
    }

}
