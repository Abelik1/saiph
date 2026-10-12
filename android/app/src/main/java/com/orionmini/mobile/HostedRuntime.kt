// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.content.Context
import android.net.Uri
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.json.*
import sefirah.network.orion.*
import java.util.UUID
import java.util.concurrent.ArrayBlockingQueue

/** One pinned Android member; no root creation or phone action dispatch. */
class HostedRuntime private constructor(private val context: Context) {
    companion object {
        @Volatile private var instance: HostedRuntime? = null
        fun get(context: Context): HostedRuntime = instance ?: synchronized(this) {
            instance ?: HostedRuntime(context.applicationContext).also { instance = it }
        }
    }
    private val prefs get() = context.getSharedPreferences("orion_hosted", 0)
    val mutex = Mutex()
    @Volatile private var generation = 0
    private var session: HostedSession? = null
    private var transport: HostedHttpTransport? = null
    private val outgoing = ArrayBlockingQueue<JsonObject>(64)
    private val cache = ClipboardCache()
    private val receipts = CommandReceipts(context)
    @Volatile var status = "Off"
        private set
    @Volatile var requestCode = ""
        private set
    @Volatile var fingerprint = ""
        private set
    @Volatile var offers: List<Pair<String, String>> = emptyList()
        private set
    var clipboard: ((String) -> Unit)? = null
    var dismiss: ((String) -> Unit)? = null
    fun enabled() = prefs.getBoolean("enabled", false)
    fun hasPackagedDefaults(): Boolean = runCatching {
        context.assets.open("hosted-defaults.json").use { it.read() != -1 }
    }.getOrDefault(false)
    fun applyPackagedDefaults() {
        if (prefs.contains("origin") || prefs.contains("device_id") || enabled()) return
        val raw = try { context.assets.open("hosted-defaults.json").use { it.readBytes() } }
            catch (_: java.io.FileNotFoundException) { return }
        check(raw.size <= 4096)
        val value = Json.parseToJsonElement(raw.toString(Charsets.UTF_8)).jsonObject
        check(value.keys == setOf("service_url", "issuer", "audience", "desktop_client_id", "android_client_id"))
        fun field(name: String) = value.getValue(name).jsonPrimitive.let { check(it.isString); it.content }
        val client = field("android_client_id")
        check(client.matches(Regex("[A-Za-z0-9_-]{8,128}")) && client != field("desktop_client_id"))
        configure(field("service_url"), field("issuer"), field("audience"), client, false)
    }
    @Synchronized fun invalidate() {
        generation++; session?.invalidate(); session = null; transport = null
        outgoing.clear(); offers = emptyList(); status = if (enabled()) "Sign in again" else "Off"
    }
    fun configure(origin: String, issuer: String, audience: String, client: String, refresh: Boolean) {
        check(!enabled() && !prefs.contains("device_id")) { "Turn off and retire the existing identity before changing deployment." }
        fun https(value: String): java.net.URI {
            check(value.length in 1..2048 && value.none { it.code <= 32 || it == '\\' })
            val uri = java.net.URI(value)
            check(uri.scheme == "https" && !uri.host.isNullOrBlank() && uri.rawUserInfo == null && uri.rawQuery == null && uri.rawFragment == null && uri.rawPath in listOf("", "/") && uri.port in -1..65535)
            return uri
        }
        https(origin); val auth = https(issuer)
        check(issuer.endsWith('/') && auth.port in listOf(-1, 443) && audience.isNotBlank() && client.isNotBlank() && audience != client)
        HostedAccount.get(context).signOut()
        check(prefs.edit().putString("origin", origin.trimEnd('/')).putString("issuer", issuer).putString("audience", audience).putString("client_id", client).putBoolean("refresh_tokens", refresh).commit())
    }
    fun setEnabled(value: Boolean) {
        check(!value || (!context.getSharedPreferences("orion", 0).contains("device_id") && prefs.contains("origin"))) { "Use an unpaired phone and save deployment settings first." }
        prefs.edit().putBoolean("enabled", value).commit()
        if (!value) { HostedAccount.get(context).cancel(); invalidate() }
    }
    private fun open(): HostedSession {
        session?.let { return it }
        check(prefs.contains("root") && !context.getSharedPreferences("orion", 0).contains("device_id"))
        val value = Json.parseToJsonElement(prefs.getString("root", "")!!).jsonObject
        val root = HostedRoot(value.getValue("deployment").jsonPrimitive.content, value.getValue("id").jsonPrimitive.content,
            value.getValue("signing").jsonPrimitive.content, value.getValue("encryption").jsonPrimitive.content)
        val id = prefs.getString("device_id", "")!!
        val keys = HostedRecipientKeys.forDeployment(context, root.deploymentId, id).load(prefs.getString("recipient", "")!!)
        val opened = HostedSession(root, id, keys, AndroidHostedTrustStore.openExisting(context, root.deploymentId, id))
        session = opened; transport = HostedHttpTransport.create(prefs.getString("origin", "")!!, opened)
        fingerprint = HostedApprovalCodes.deviceFingerprint(opened.enrollment().getValue("device").jsonObject)
        return opened
    }
    suspend fun enroll(code: String, comparison: String) = mutex.withLock {
        check(enabled() && !prefs.contains("device_id") && !context.getSharedPreferences("orion", 0).contains("device_id"))
        val token = HostedAccount.get(context).token()
        val root = HostedApprovalCodes.trust(code, comparison)
        val id = "dev_" + UUID.randomUUID().toString().replace("-", "")
        // Record identity intent before creating anything. Partial enrollment is
        // preserved and requires explicit retirement, never silent replacement.
        check(prefs.edit().putString("device_id", id).putString("root", buildJsonObject {
            put("deployment", root.deploymentId); put("id", root.deviceId); put("signing", root.signingPublic); put("encryption", root.encryptionPublic)
        }.toString()).commit())
        Security.ensureKey()
        val keys = HostedRecipientKeys.forDeployment(context, root.deploymentId, id).create()
        check(prefs.edit().putString("recipient", HostedEnvelope.exportPublic(keys.recipient)).commit())
        val current = HostedSession(root, id, keys, AndroidHostedTrustStore.create(context, root.deploymentId, id))
        session = current; transport = HostedHttpTransport.create(prefs.getString("origin", "")!!, current)
        requestCode = HostedApprovalCodes.request(current)
        fingerprint = HostedApprovalCodes.deviceFingerprint(current.enrollment().getValue("device").jsonObject)
        transport!!.submitEnrollment(token)
        status = "Waiting for root approval"
    }
    suspend fun freshRequest() = mutex.withLock {
        check(enabled()); val token = HostedAccount.get(context).token(); val current = open()
        requestCode = HostedApprovalCodes.request(current); transport!!.submitEnrollment(token)
    }
    fun enqueue(type: String, value: JsonObject): Boolean {
        if (!enabled() || status != "Connected" || !HostedAccount.get(context).signedIn()) return false
        val access = OrionPermissions.read(context)
        val payload = when (type) {
            "clipboard.text" -> {
                if (!access.clipboard) return false
                val text = value["text"]?.jsonPrimitive?.content ?: return false
                val bytes = text.toByteArray(Charsets.UTF_8)
                if (bytes.size !in 1..16384 || !cache.claim("text/plain", ClipboardCache.hash(bytes))) return false
                buildJsonObject { put("type", type); put("text", text); put("sha256", ClipboardCache.hash(bytes)) }
            }
            "notification.upsert", "notification.remove" -> if (access.notifications) value else return false
            else -> return false
        }
        return outgoing.offer(payload)
    }
    suspend fun step() = mutex.withLock {
        if (!enabled()) { invalidate(); return@withLock }
        if (!prefs.contains("device_id")) { status = "Scan or paste the root code"; return@withLock }
        val token = try { HostedAccount.get(context).token() } catch (_: Exception) { invalidate(); return@withLock }
        val epoch = generation
        fun gate() { check(epoch == generation && enabled() && HostedAccount.get(context).signedIn()) }
        val current = try { open() } catch (_: Exception) { status = "Protected identity unavailable; keys were kept"; return@withLock }
        try { transport!!.refreshTrust(token) } catch (_: Exception) {
            outgoing.clear(); offers = emptyList(); status = "Waiting for root approval or renewal"; return@withLock
        }
        gate(); status = "Connected"
        while (true) {
            val payload = outgoing.poll() ?: break
            val type = payload["type"]?.jsonPrimitive?.content
            val access = OrionPermissions.read(context)
            if (type == "clipboard.text" && !access.clipboard || type?.startsWith("notification.") == true && !access.notifications) continue
            gate(); transport!!.send(current.root.deviceId, payload)
        }
        gate(); transport!!.pollIntoEncryptedInbox()
        val files = mutableListOf<Pair<String, String>>()
        for (envelope in current.pendingIncoming()) {
            gate()
            val id = envelope.getValue("header").jsonObject.getValue("id").jsonPrimitive.content
            val payload = runCatching { current.authenticate(envelope) }.getOrNull() ?: continue
            when (payload["type"]?.jsonPrimitive?.content) {
                "file.encrypted" -> files += id to payload.getValue("name").jsonPrimitive.content.take(255)
                "clipboard.text" -> {
                    check(payload.keys == setOf("type", "text", "sha256"))
                    val text = payload.getValue("text").jsonPrimitive.content
                    val raw = text.toByteArray(Charsets.UTF_8)
                    check(raw.size in 1..16384 && ClipboardCache.hash(raw) == payload.getValue("sha256").jsonPrimitive.content)
                    if (OrionPermissions.read(context).clipboard && receipts.claim("hosted:$id") && cache.claim("text/plain", ClipboardCache.hash(raw))) clipboard?.invoke(text)
                }
                "notification.dismiss" -> {
                    check(envelope.getValue("header").jsonObject["source"] == JsonPrimitive(current.root.deviceId))
                    check(payload.keys == setOf("type", "key"))
                    val key = payload.getValue("key").jsonPrimitive.content
                    check(Regex("[A-Za-z0-9._:|/+=@-]{1,256}").matches(key))
                    if (OrionPermissions.read(context).notifications && receipts.claim("hosted:$id")) dismiss?.invoke(key)
                }
                // Decryption does not authorize SMS, calls or arbitrary actions.
            }
            if (payload["type"] != JsonPrimitive("file.encrypted")) current.completeIncoming(id)
        }
        gate(); offers = files
    }
    suspend fun sendFile(uri: Uri) = mutex.withLock {
        check(enabled() && HostedAccount.get(context).signedIn()); val current = open(); current.currentMembers()
        context.contentResolver.openInputStream(uri)!!.use { input ->
            var name = "shared-file"
            context.contentResolver.query(uri, arrayOf(android.provider.OpenableColumns.DISPLAY_NAME), null, null, null)?.use { if (it.moveToFirst()) name = it.getString(0) }
            HostedAttachments.send(current, transport!!, input, name, "application/octet-stream")
        }
    }
    suspend fun saveFile(id: String, uri: Uri) = mutex.withLock {
        check(enabled() && HostedAccount.get(context).signedIn()); val current = open()
        val envelope = current.pendingIncoming().first { it.getValue("header").jsonObject.getValue("id").jsonPrimitive.content == id }
        // Verify the complete encrypted file privately before opening the user's destination.
        val verified = HostedAttachments.receive(current, transport!!, envelope, context.noBackupFilesDir)
        try {
            check(receipts.claim("hosted:$id")) { "This offer was already saved. Check your files." }
            context.contentResolver.openOutputStream(uri, "w")!!.use { output -> verified.inputStream().use { it.copyTo(output) } }
            current.completeIncoming(id)
            offers = offers.filterNot { it.first == id }
        } finally { verified.delete() }
    }
    fun retire() {
        check(!enabled()); HostedAccount.get(context).signOut(); invalidate()
        // Keystore keys and encrypted trust history stay available for explicit
        // recovery. A newly enrolled member gets a fresh unique device ID.
        prefs.edit().remove("device_id").remove("root").remove("recipient").commit()
    }
}
