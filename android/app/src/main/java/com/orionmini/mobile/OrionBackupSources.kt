package com.orionmini.mobile

import android.content.ContentUris
import android.content.Context
import android.net.Uri
import android.os.Build
import android.os.StatFs
import android.provider.DocumentsContract
import android.provider.MediaStore
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import java.io.File
import java.security.MessageDigest

/** Materialize content URIs into a stable, isolated tree, never the entire filesDir. */
internal class OrionBackupSources(private val context: Context) {
    class PermissionNeeded : Exception()
    class StorageNeeded : Exception()
    private val base = File(context.filesDir, "orion-backup-content").apply { mkdirs() }
    private val seen = mutableSetOf<String>()
    private val seenUris = mutableSetOf<String>()
    private var entries = 0

    suspend fun stage(): File {
        File(base, "received").mkdirs()
        if (Build.VERSION.SDK_INT >= 29) {
            val collection = MediaStore.Downloads.EXTERNAL_CONTENT_URI
            // Only Orion-created rows are readable without broad storage permission. Explicitly
            // filter owner too, because a granted media permission must not expand this scope.
            val projection = arrayOf(MediaStore.Downloads._ID, MediaStore.Downloads.DISPLAY_NAME,
                MediaStore.Downloads.SIZE, MediaStore.Downloads.DATE_MODIFIED)
            context.contentResolver.query(collection, projection,
                "${MediaStore.Downloads.RELATIVE_PATH} = ? AND ${MediaStore.Downloads.IS_PENDING} = 0 AND ${MediaStore.Downloads.OWNER_PACKAGE_NAME} = ?",
                arrayOf("Download/Orion/", context.packageName), null)?.use { rows ->
                while (rows.moveToNext()) copy(ContentUris.withAppendedId(collection, rows.getLong(0)),
                    "received", rows.getString(1) ?: "file", rows.getLong(2), rows.getLong(3) * 1000)
            } ?: throw PermissionNeeded()
        }
        // Retained completion URIs also support providers/storage volumes absent from the query.
        if (Build.VERSION.SDK_INT < 29) {
            val receipts = context.getSharedPreferences("orion_file_transfers", Context.MODE_PRIVATE).all
            for ((key, value) in receipts) if (key.startsWith("received:") && value is String) {
                val uri = Uri.parse(value)
                if (uri.toString() !in seenUris) copy(uri, "received", "received-file", -1, 0)
            }
        }
        val folders = context.getSharedPreferences("orion_backup", Context.MODE_PRIVATE).getStringSet("folders", emptySet()).orEmpty().toSet()
        val grants = context.contentResolver.persistedUriPermissions.filter { it.isReadPermission }.map { it.uri.toString() }.toSet()
        for (folder in folders) {
            if (folder !in grants) throw PermissionNeeded()
            val tree = Uri.parse(folder)
            walk(tree, DocumentsContract.getTreeDocumentId(tree), "folders/${digest(folder)}", 0)
        }
        // Clean only our mirror after all providers have been read successfully. Remote snapshots
        // remain immutable; removing a folder from Advanced never deletes the user's files.
        base.walkBottomUp().filter { it.isFile && it.relativeTo(base).invariantSeparatorsPath !in seen }.forEach { it.delete() }
        return base
    }

    private suspend fun walk(tree: Uri, parent: String, destination: String, depth: Int) {
        if (depth > 128) throw PermissionNeeded()
        val children = DocumentsContract.buildChildDocumentsUriUsingTree(tree, parent)
        val columns = arrayOf(DocumentsContract.Document.COLUMN_DOCUMENT_ID, DocumentsContract.Document.COLUMN_DISPLAY_NAME,
            DocumentsContract.Document.COLUMN_MIME_TYPE, DocumentsContract.Document.COLUMN_SIZE, DocumentsContract.Document.COLUMN_LAST_MODIFIED,
            DocumentsContract.Document.COLUMN_FLAGS)
        try {
            context.contentResolver.query(children, columns, null, null, null)?.use { rows ->
                while (rows.moveToNext()) {
                    currentCoroutineContext().ensureActive()
                    if (++entries > 100000) throw StorageNeeded()
                    val id = rows.getString(0)
                    val name = rows.getString(1) ?: "file"
                    if (rows.getString(2) == DocumentsContract.Document.MIME_TYPE_DIR) {
                        val path = "$destination/${safeName(name)}-${digest(id).take(12)}"
                        File(base, path).mkdirs(); walk(tree, id, path, depth + 1)
                    } else {
                        if (rows.getInt(5) and DocumentsContract.Document.FLAG_VIRTUAL_DOCUMENT != 0) throw PermissionNeeded()
                        copy(DocumentsContract.buildDocumentUriUsingTree(tree, id), destination, name,
                            if (rows.isNull(3)) -1 else rows.getLong(3), if (rows.isNull(4)) 0 else rows.getLong(4))
                    }
                }
            } ?: throw PermissionNeeded()
        } catch (_: SecurityException) { throw PermissionNeeded() }
    }

    private suspend fun copy(uri: Uri, directory: String, name: String, size: Long, modified: Long) {
        if (!seenUris.add(uri.toString())) return
        val relative = "$directory/${safeName(name)}-${digest(uri.toString())}"
        if (!seen.add(relative)) return
        val destination = File(base, relative)
        if (size >= 0 && modified > 0 && destination.isFile && destination.length() == size && destination.lastModified() == modified) return
        val pending = File(destination.parentFile, destination.name + ".pending")
        destination.parentFile?.mkdirs()
        try {
            if (size > 0 && StatFs(base.absolutePath).availableBytes < size + RESERVE) throw StorageNeeded()
            val input = try { context.contentResolver.openInputStream(uri) ?: throw PermissionNeeded() }
                catch (_: SecurityException) { throw PermissionNeeded() }
            input.use { source -> pending.outputStream().use { sink ->
                val buffer = ByteArray(1024 * 1024)
                var total = 0L
                while (true) {
                    currentCoroutineContext().ensureActive()
                    val count = source.read(buffer); if (count < 0) break
                    if (StatFs(base.absolutePath).availableBytes < RESERVE) throw StorageNeeded()
                    sink.write(buffer, 0, count); total += count
                }
                if (size >= 0 && total != size) throw PermissionNeeded()
            } }
            check(pending.renameTo(destination))
            if (modified > 0) destination.setLastModified(modified)
        } finally { pending.delete() }
    }

    companion object {
        private const val RESERVE = 128L * 1024 * 1024
        internal fun safeName(value: String): String = value.replace(Regex("[^\\p{L}\\p{N}._ -]"), "_").trim('.').take(100).ifEmpty { "file" }
        private fun digest(value: String): String = MessageDigest.getInstance("SHA-256").digest(value.toByteArray()).joinToString("") { "%02x".format(it) }
    }
}
