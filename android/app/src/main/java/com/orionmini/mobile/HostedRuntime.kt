// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.core.app.NotificationCompat
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.json.*
import sefirah.network.orion.*
import java.util.UUID
import java.util.concurrent.ArrayBlockingQueue

/**
 * One pinned Android member; no root creation. Phone actions (texts and calls)
 * run only for approved computers that subscribed, only while the owner's
 * "Texts and calls" switch is on and only with the matching Android permission.
 */
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
    // Phone data for one subscribed computer each: call state and answers first,
    // then conversation sync, which is bulk and lower priority than everything else.
    private class Delivery(val target: String, val payload: JsonObject, val delivered: () -> Unit)
    private val calls = ArrayBlockingQueue<Delivery>(64)
    private val texts = ArrayBlockingQueue<Delivery>(256)
    /** Computers that asked for texts and calls: device ID to display name and time. */
    private val subscriptions = java.util.concurrent.ConcurrentHashMap<String, Pair<String, Long>>()
    @Volatile private var members: Set<String> = emptySet()
    /** Wakes the sync loop for a ringing call or an answer a computer is waiting for. */
    val wake = Channel<Unit>(Channel.CONFLATED)
    @Volatile var ringing = false
        private set
    private var advertised: List<String>? = null
    private var advertisedAt = 0L
    /** Installed by the sync service; runs one validated phone action (event ID, sender, action). */
    var phone: ((String, String, HostedPhoneCommand) -> Unit)? = null
    /** Current roster members that subscribed in the last ten minutes, with their names. */
    fun subscribers(): Map<String, String> {
        val now = System.currentTimeMillis()
        return subscriptions.filter { (id, value) -> id in members && now - value.second in 0..HostedPhoneFrames.SUBSCRIPTION_MILLIS }
            .mapValues { it.value.first }
    }
    fun label(device: String) = subscriptions[device]?.first.orEmpty()
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
    /** The owner's opt-in for texts and calls on the root computer; off by default. */
    fun textsAndCalls() = prefs.getBoolean("texts_and_calls", false)
    fun setTextsAndCalls(value: Boolean) {
        check(prefs.edit().putBoolean("texts_and_calls", value).commit())
        if (!value) { texts.clear(); calls.clear(); ringing = false }
        advertised = null
    }
    fun textBacklog() = texts.isNotEmpty() || calls.isNotEmpty()
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
        outgoing.clear(); texts.clear(); calls.clear(); ringing = false; advertised = null
        subscriptions.clear(); members = emptySet()
        offers = emptyList(); status = if (enabled()) "Sign in again" else "Off"
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
        offer(token)
        UsageAnalytics.count(context, "hosted_enrolled")
        status = "Waiting for root approval"
    }
    suspend fun freshRequest() = mutex.withLock {
        check(enabled()); val token = HostedAccount.get(context).token(); val current = open()
        requestCode = HostedApprovalCodes.request(current); transport!!.submitEnrollment(token); offer(token)
    }
    /** Best effort: an older service has no offered requests, and the code can still be shared. */
    private fun offer(token: String) { runCatching { transport!!.offerRequest(token, requestCode) } }
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
        val queued = outgoing.offer(payload)
        if (queued) UsageAnalytics.count(context, if (type == "clipboard.text") "clipboard_sent" else "notification_shared")
        return queued
    }
    /**
     * Texts and calls for one subscribed computer; false when off, not permitted,
     * not subscribed or the queue is full. Call state and answers go first.
     */
    fun enqueuePhone(target: String, value: JsonObject, delivered: () -> Unit): Boolean {
        if (!enabled() || status != "Connected" || !HostedAccount.get(context).signedIn() || target !in subscribers()) return false
        val type = (value["type"] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: return false
        if (!HostedPhoneFrames.mayPublish(type, OrionPermissions.read(context), textsAndCalls()) || type == HostedPhoneFrames.CAPABILITIES
            || !HostedPhoneFrames.fits(value)) return false
        if (type.startsWith("sms.")) return texts.offer(Delivery(target, value, delivered))
        if (type == "call.state") ringing = value["state"] == JsonPrimitive("ringing")
        return calls.offer(Delivery(target, value, delivered)).also { if (it) wake.trySend(Unit) }
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
        runCatching { watchMembers(current) }
        members = current.currentMembers().keys - current.deviceId
        subscriptions.keys.retainAll(members) // A revoked computer stops receiving at once.
        // Tell every approved device what this phone offers, on change and every two
        // minutes; computers answer with phone.subscribe. The roster has no device kinds.
        val offered = HostedPhoneFrames.capabilities(OrionPermissions.read(context), textsAndCalls())
        if (offered != advertised || System.currentTimeMillis() - advertisedAt > 120_000) {
            for (member in members) { gate(); transport!!.send(member, HostedPhoneFrames.capabilitiesPayload(offered)) }
            advertised = offered; advertisedAt = System.currentTimeMillis()
        }
        while (true) {
            val payload = outgoing.poll() ?: break
            val type = payload["type"]?.jsonPrimitive?.content
            val access = OrionPermissions.read(context)
            if (type == "clipboard.text" && !access.clipboard || type?.startsWith("notification.") == true && !access.notifications) continue
            gate(); transport!!.send(current.root.deviceId, payload)
        }
        // Each phone delivery names one computer, which must still be subscribed and approved.
        fun deliver(item: Delivery) {
            val type = item.payload.getValue("type").jsonPrimitive.content
            if (item.target !in subscribers() || !HostedPhoneFrames.mayPublish(type, OrionPermissions.read(context), textsAndCalls())) return
            gate(); transport!!.send(item.target, item.payload)
            runCatching(item.delivered)
        }
        while (true) deliver(calls.poll() ?: break)
        // A bounded share of the conversation sync per pass; the rest follows shortly.
        repeat(32) { deliver(texts.poll() ?: return@repeat) }
        gate(); transport!!.pollIntoEncryptedInbox()
        val files = mutableListOf<Pair<String, String>>()
        for (envelope in current.pendingIncoming()) {
            gate()
            val id = envelope.getValue("header").jsonObject.getValue("id").jsonPrimitive.content
            val payload = runCatching { current.authenticate(envelope) }.getOrNull() ?: continue
            val source = envelope.getValue("header").jsonObject["source"]?.jsonPrimitive?.content.orEmpty()
            when (val type = payload["type"]?.jsonPrimitive?.content.orEmpty()) {
                "file.encrypted" -> files += id to payload.getValue("name").jsonPrimitive.content.take(255)
                "clipboard.text" -> {
                    check(payload.keys == setOf("type", "text", "sha256"))
                    val text = payload.getValue("text").jsonPrimitive.content
                    val raw = text.toByteArray(Charsets.UTF_8)
                    check(raw.size in 1..16384 && ClipboardCache.hash(raw) == payload.getValue("sha256").jsonPrimitive.content)
                    if (OrionPermissions.read(context).clipboard && receipts.claim("hosted:$id") && cache.claim("text/plain", ClipboardCache.hash(raw))) {
                        clipboard?.invoke(text); UsageAnalytics.count(context, "clipboard_received")
                    }
                }
                "notification.dismiss" -> {
                    check(envelope.getValue("header").jsonObject["source"] == JsonPrimitive(current.root.deviceId))
                    check(payload.keys == setOf("type", "key"))
                    val key = payload.getValue("key").jsonPrimitive.content
                    check(Regex("[A-Za-z0-9._:|/+=@-]{1,256}").matches(key))
                    if (OrionPermissions.read(context).notifications && receipts.claim("hosted:$id")) dismiss?.invoke(key)
                }
                // A computer, root or not, asks for texts and calls under its display name.
                HostedPhoneFrames.SUBSCRIBE -> HostedPhoneFrames.subscribe(payload)?.let { name ->
                    if (source in members) subscriptions[source] = name to System.currentTimeMillis()
                }
                // Decryption proves origin only. Texts and calls need a subscribed roster member
                // as sender, the owner's switch and the Android permission, checked at execution.
                in HostedPhoneFrames.COMMAND_CAPABILITY -> {
                    val command = HostedPhoneFrames.command(payload)
                    // Texts and calls run at most once; reads (sync, open, search, history) may repeat.
                    if (command != null && HostedPhoneFrames.allowed(type, source, subscribers().keys, OrionPermissions.read(context), textsAndCalls())
                        && (!HostedPhoneFrames.isEffect(command) || receipts.claim("hosted:$id"))) runCatching { phone?.invoke(id, source, command) }
                }
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
        UsageAnalytics.count(context, "hosted_file_send")
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
            UsageAnalytics.count(context, "hosted_file_save")
        } finally { verified.delete() }
    }
    fun retire() {
        check(!enabled()); HostedAccount.get(context).signOut(); invalidate()
        // Keystore keys and encrypted trust history stay available for explicit
        // recovery. A newly enrolled member gets a fresh unique device ID.
        prefs.edit().remove("device_id").remove("root").remove("recipient").remove("seen_members").remove("texts_and_calls").commit()
        HostedSmsKnown.clearAll(context)
    }

    /**
     * Alert on every change to the root-signed device list. The first verified
     * list is the baseline; afterwards an added device raises a high-priority
     * notification, so an approval made on an unattended computer is noticed.
     */
    private fun watchMembers(current: HostedSession) {
        val members = current.currentMembers().keys.filter { it != current.deviceId }.sorted()
        val seen = prefs.getString("seen_members", null)
        val joined = members.joinToString(",")
        if (seen == joined) return
        check(prefs.edit().putString("seen_members", joined).commit())
        if (seen == null) return
        val before = seen.split(',').filter { it.isNotEmpty() }.toSet()
        val added = members.count { it !in before }
        val removed = before.count { it !in members }
        val now = System.currentTimeMillis()
        val events = securityEventRecords().toMutableList()
        if (added > 0) events.add(0, "$now:added:$added")
        if (removed > 0) events.add(0, "$now:removed:$removed")
        prefs.edit().putString("security_events", events.take(20).joinToString("\n")).apply()
        if (added > 0) alert(if (added == 1) "A new device was added to your Saiph account" else "$added new devices were added to your Saiph account",
            "If you didn't approve this on your computer, remove the device there now and change your password.")
        else alert("A device was removed from your Saiph account", "It no longer receives your clipboard, notifications, files, texts or calls.")
    }
    private fun securityEventRecords() = prefs.getString("security_events", "")!!.split('\n').filter { it.matches(Regex("\\d{1,15}:(added|removed):\\d{1,3}")) }
    /** Recent device-list changes for the Hosted screen, newest first. */
    fun securityEvents(): List<String> = securityEventRecords().map { record ->
        val (time, kind, count) = record.split(':')
        val label = java.text.DateFormat.getDateTimeInstance().format(java.util.Date(time.toLong()))
        (if (kind == "added") "Device added" else "Device removed") + (if (count != "1") " ($count)" else "") + " · $label"
    }
    private fun alert(title: String, body: String) {
        val manager = context.getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel("orion_security", "Saiph security alerts", NotificationManager.IMPORTANCE_HIGH))
        val open = PendingIntent.getActivity(context, 44, Intent(context, HostedActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        runCatching {
            manager.notify(44, NotificationCompat.Builder(context, "orion_security").setSmallIcon(android.R.drawable.ic_dialog_alert)
                .setContentTitle(title).setContentText(body).setStyle(NotificationCompat.BigTextStyle().bigText(body))
                .setContentIntent(open).setAutoCancel(true).setPriority(NotificationCompat.PRIORITY_HIGH).build())
        }
    }
}
