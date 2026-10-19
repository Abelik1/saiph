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
import java.io.File
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
    private var lastEnrollmentAttempt = 0L
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
    private var advertisedScreen: List<String>? = null
    private var advertisedFeatures: List<String>? = null
    private var advertisedAt = 0L
    /** Installed by the sync service; runs one validated phone action (event ID, sender, action). */
    var phone: ((String, String, HostedPhoneCommand) -> Unit)? = null
    /** Installed by the sync service; runs one validated quick action (sender, action). */
    var control: ((String, PhoneControlCommand) -> Unit)? = null
    /** Installed by the sync service; presses a notification button, replies to it or opens it. */
    var notificationCommand: ((HostedNotificationCommand) -> Unit)? = null
    // Status for subscribed computers, with the same rules as a Hub phone; media is Cloud's own shape.
    private val statusPublisher = PhoneStatusPublisher()
    private val mediaVersion = java.util.concurrent.atomic.AtomicInteger()
    private val mediaSent = mutableMapOf<String, Int>()
    private var mediaSentAt = 0L
    @Volatile private var pauseAnnounced = false
    /** The merged media sessions changed; the next pass sends them, at most every two seconds. */
    fun mediaChanged() { mediaVersion.incrementAndGet(); wake.trySend(Unit) }
    /** Current roster members that subscribed in the last ten minutes, with their names. */
    fun subscribers(): Map<String, String> {
        val now = System.currentTimeMillis()
        return subscriptions.filter { (id, value) -> id in members && now - value.second in 0..HostedPhoneFrames.SUBSCRIPTION_MILLIS }
            .mapValues { it.value.first }
    }
    fun label(device: String) = subscriptions[device]?.first.orEmpty()
    private val cache = ClipboardCache()
    private val receipts = CommandReceipts(context)
    /** Sealed answers for one device each: file requests, refusals and withdrawals (LanFiles.kt). */
    private val replies = ArrayBlockingQueue<Pair<String, JsonObject>>(32)
    /** Files directly over the local network; incoming ones wait in private storage for Save. */
    internal val lan = LanTransfers(File(context.noBackupFilesDir, "lan-files")) { target, payload ->
        if (replies.offer(target to payload)) wake.trySend(Unit)
    }
    @Volatile var status = "Off"
    /** Last /v1/access answer, for the free trial notice only; memory only. */
    @Volatile internal var access: HostedTrial.Access? = null
    private var accessAt = 0L
        private set
    @Volatile var requestCode = ""
        private set
    @Volatile var fingerprint = ""
        private set
    @Volatile var offers: List<Pair<String, String>> = emptyList()
        private set
    var clipboard: ((String, () -> Boolean) -> Unit)? = null
    var clipboardImage: ((File, () -> Boolean) -> Unit)? = null
    private class ClipboardImage(val mime: String, val file: File, val digest: String, val until: Long) {
        val uploads = mutableMapOf<String, HostedAttachments.Prepared>()
        val sent = mutableSetOf<String>()
    }
    @Volatile private var pendingImage: ClipboardImage? = null
    @Volatile var clipboardNotice = ""
        private set
    @Synchronized private fun clearClipboardImage() { pendingImage?.file?.delete(); pendingImage = null }
    @Synchronized private fun clearClipboardImage(image: ClipboardImage) { if (pendingImage === image) clearClipboardImage() }
    /** Takes ownership only on success. Never holds more than the latest local image. */
    @Synchronized fun enqueueClipboardImage(mime: String, file: File): Boolean {
        if (!enabled() || status != "Connected" || !HostedAccount.get(context).signedIn() || !OrionPermissions.read(context).clipboard) return false
        if (mime !in HostedClipboardImages.extensions || file.length() !in 1..HostedClipboardImages.MAX_BYTES.toLong() ||
            file.canonicalFile.parentFile != context.cacheDir.canonicalFile || !file.name.startsWith("orion-clipboard-") || java.nio.file.Files.isSymbolicLink(file.toPath())) {
            clipboardNotice = "This clipboard image is unsupported or too large. Send it as a file."
            return false
        }
        val digest = file.inputStream().use { input ->
            val hash = java.security.MessageDigest.getInstance("SHA-256"); val buffer = ByteArray(65536)
            while (true) { val count = input.read(buffer); if (count < 0) break; hash.update(buffer, 0, count) }
            hash.digest().joinToString("") { "%02x".format(it) }
        }
        if (!cache.claim(mime, digest)) return false
        clearClipboardImage()
        outgoing.removeIf { it["type"] == JsonPrimitive("clipboard.text") }
        pendingImage = ClipboardImage(mime, file, digest, android.os.SystemClock.elapsedRealtime() + 30_000)
        clipboardNotice = ""; wake.trySend(Unit)
        return true
    }
    private fun syncClipboardImage(current: HostedSession, epoch: Int) {
        val image = pendingImage ?: return
        fun allowed(target: String): Boolean = runCatching {
            pendingImage === image && android.os.SystemClock.elapsedRealtime() < image.until && epoch == generation && session === current &&
                enabled() && HostedAccount.get(context).signedIn() && OrionPermissions.read(context).clipboard && target in current.currentMembers()
        }.getOrDefault(false)
        if (android.os.SystemClock.elapsedRealtime() >= image.until || !OrionPermissions.read(context).clipboard) { clearClipboardImage(image); return }
        if (!HostedClipboardImages.valid(image.mime, image.file)) {
            clearClipboardImage(image); clipboardNotice = "This clipboard image is unsupported or too large. Send it as a file."; return
        }
        for (target in current.currentMembers().keys - current.deviceId) {
            if (target in image.sent) continue
            if (!allowed(target)) return
            val checkpoint = current.pagingCheckpoint()
            var prepared = image.uploads[target]
            if (prepared != null && (prepared.descriptor["roster_version"] != JsonPrimitive(checkpoint.version) || prepared.descriptor["roster_hash"] != JsonPrimitive(checkpoint.digest))) {
                image.uploads.remove(target); prepared = null
            }
            try {
                if (prepared == null) {
                    val ttl = ((image.until - android.os.SystemClock.elapsedRealtime()) / 1000).toInt().coerceAtMost(30)
                    if (ttl < 1) return
                    prepared = image.file.inputStream().use {
                        HostedAttachments.prepare(current, it, "clipboard." + HostedClipboardImages.extensions.getValue(image.mime), image.mime,
                            target, kind = "clipboard.image", ttlSeconds = ttl) { check(allowed(target)) }
                    }
                    image.uploads[target] = prepared
                }
                val upload = prepared
                HostedAttachments.upload(transport!!, upload) {
                    check(allowed(target)); val fresh = current.pagingCheckpoint()
                    check(upload.descriptor["roster_version"] == JsonPrimitive(fresh.version) && upload.descriptor["roster_hash"] == JsonPrimitive(fresh.digest))
                }
                image.sent.add(target)
            } catch (_: Exception) {
                clipboardNotice = "Image clipboard could not finish. Copy the image again if it does not arrive."; return
            }
        }
        synchronized(this) { if (pendingImage === image) { clearClipboardImage(); clipboardNotice = "" } }
    }
    private fun receiveClipboardImage(current: HostedSession, envelope: JsonObject, payload: JsonObject, epoch: Int, source: String, id: String) {
        fun allowed(): Boolean = runCatching {
            epoch == generation && session === current && enabled() && HostedAccount.get(context).signedIn() &&
                System.currentTimeMillis() / 1000 < envelope.getValue("header").jsonObject.getValue("expires_at").jsonPrimitive.long &&
                OrionPermissions.read(context).clipboard && source in current.currentMembers()
        }.getOrDefault(false)
        if (!allowed()) return
        val verified = HostedAttachments.receive(current, transport!!, envelope, context.noBackupFilesDir)
        try {
            val mime = payload.getValue("mime").jsonPrimitive.content
            check(HostedClipboardImages.valid(mime, verified))
            current.authenticate(envelope)
            if (!allowed() || !receipts.claim("hosted:$id")) return
            val folder = File(context.cacheDir, "hosted-clipboard").apply { check(isDirectory || mkdir()) }
            // Bounded owned URI cache; successful clipboard URIs survive this download.
            folder.listFiles()?.filter { it.name.startsWith("received-") }?.sortedByDescending { it.lastModified() }?.drop(3)?.forEach { it.delete() }
            val image = File.createTempFile("received-", "." + HostedClipboardImages.extensions.getValue(mime), folder)
            try {
                verified.inputStream().use { input -> image.outputStream().use { input.copyTo(it) } }
                val digest = payload.getValue("sha256").jsonPrimitive.content
                val effect = clipboardImage
                if (effect == null) image.delete()
                else effect(image) { allowed() && cache.claim(mime, digest) }
            } catch (failure: Exception) { image.delete(); throw failure }
        } finally { verified.delete() }
    }
    var dismiss: ((String) -> Unit)? = null
    fun enabled() = prefs.getBoolean("enabled", false)
    fun clipboardWorkerIdentity(): String = runCatching {
        val current = session ?: return ""
        if (!enabled() || status != "Connected" || !HostedAccount.get(context).signedIn() || !OrionPermissions.read(context).clipboard) return ""
        check(current.deviceId in current.currentMembers())
        current.deviceId
    }.getOrDefault("")
    @Volatile private var identityUnavailable = false
    /** Navigation only. Sending still requires a fresh, verified roster in HostedSession. */
    internal fun setupStage() = HostedSetup.stage(prefs.contains("device_id"), identityUnavailable,
        prefs.getBoolean("approval_verified", false))
    /** The owner's opt-in for texts and calls on the root computer; off by default. */
    @Volatile internal var photosRevision = 0
    fun photosShared() = prefs.getBoolean("photos_shared", false)
    fun setPhotosShared(value: Boolean) {
        check(prefs.edit().putBoolean("photos_shared", value).commit())
        photosRevision++
        advertised = null
    }
    fun textsAndCalls() = prefs.getBoolean("texts_and_calls", false)
    fun setTextsAndCalls(value: Boolean) {
        check(prefs.edit().putBoolean("texts_and_calls", value).commit())
        if (!value) { texts.clear(); calls.clear(); ringing = false }
        advertised = null
    }
    fun textBacklog() = texts.isNotEmpty() || calls.isNotEmpty()
    /** Battery, network, sound, Do Not Disturb and media for approved computers, with their quick actions. On by default. */
    fun statusShared() = PhoneQuickControls.shared(context)
    fun setStatusShared(value: Boolean) { PhoneQuickControls.setShared(context, value); statusPublisher.invalidate(); wake.trySend(Unit) }
    /** Phone Link's "Sync over mobile data": off pauses Saiph Cloud while the phone is on a metered network. */
    fun mobileDataAllowed() = prefs.getBoolean("mobile_data", true)
    fun setMobileData(value: Boolean) { check(prefs.edit().putBoolean("mobile_data", value).commit()); statusPublisher.invalidate(); wake.trySend(Unit) }
    fun pausedOnMobileData() = !mobileDataAllowed() && PhoneQuickControls.metered(context)
    private fun controlsNow(): List<String> = PhoneQuickControls.controls(context, PhoneTransport.HOSTED)
    /** A quick action's answer (the wallpaper) for the computer that asked. */
    fun enqueueAnswer(target: String, value: JsonObject): Boolean {
        if (!enabled() || status != "Connected" || target !in subscribers() || !statusShared() || !HostedPhoneFrames.fits(value)) return false
        return calls.offer(Delivery(target, value) {}).also { if (it) wake.trySend(Unit) }
    }
    /** Status on change (see [PhoneStatusFrames.due]) and media on change, to every subscribed computer. */
    private fun syncStatus(send: (String, JsonObject) -> Unit, paused: Boolean) {
        val targets = subscribers().keys
        mediaSent.keys.retainAll(targets)
        val current = PhoneQuickControls.current(context, PhoneTransport.HOSTED, mobileDataAllowed(), paused)
        val now = System.currentTimeMillis()
        // A pause notice goes to every computer; otherwise only what is due, and to computers that missed it.
        val payload = PhoneStatusFrames.payload(current)
        val signal = PhoneStatusFrames.signalPayload(current)  // Older desktops ignore it.
        statusPublisher.sync(targets, current, paused, now) { target -> send(target, payload); send(target, signal); true }
        if (targets.isEmpty()) return
        val controls = current.controls
        if ("media" !in controls) return
        val version = mediaVersion.get()
        val stale = targets.filter { mediaSent[it] != version }
        if (stale.isEmpty() || now - mediaSentAt in 0 until 2_000) return
        val media = PhoneStatusFrames.media(OrionPhoneFeatures.media.state())
        for (target in stale) { send(target, media); mediaSent[target] = version }
        mediaSentAt = now
    }
    fun hasPackagedDefaults(): Boolean = runCatching {
        context.assets.open("hosted-defaults.json").use { it.read() != -1 }
    }.getOrDefault(false)
    fun applyPackagedDefaults() {
        val raw = try { context.assets.open("hosted-defaults.json").use { it.readBytes() } }
            catch (_: java.io.FileNotFoundException) { return }
        check(raw.size <= 4096)
        val value = Json.parseToJsonElement(raw.toString(Charsets.UTF_8)).jsonObject
        check(value.keys == setOf("service_url", "issuer", "audience", "desktop_client_id", "android_client_id"))
        fun field(name: String) = value.getValue(name).jsonPrimitive.let { check(it.isString); it.content }
        val client = field("android_client_id")
        check(client.matches(Regex("[A-Za-z0-9_-]{8,128}")) && client != field("desktop_client_id"))
        if (prefs.contains("origin") || prefs.contains("device_id") || enabled()) {
            // Migrate only this build's deployment. Never change a custom issuer,
            // approved identity or an explicitly signed-out account.
            if (prefs.getString("origin", "") == field("service_url").trimEnd('/') &&
                prefs.getString("issuer", "") == field("issuer") &&
                prefs.getString("audience", "") == field("audience") && prefs.getString("client_id", "") == client)
                check(prefs.edit().putBoolean("refresh_tokens", true).commit())
            return
        }
        configure(field("service_url"), field("issuer"), field("audience"), client, true)
    }
    @Synchronized fun invalidate() {
        clearClipboardImage()
        generation++; session?.invalidate(); session = null; transport = null
        outgoing.clear(); texts.clear(); calls.clear(); ringing = false; advertised = null; advertisedScreen = null; advertisedFeatures = null
        subscriptions.clear(); members = emptySet(); SessionOffers.clear(); RequestPrompts.clearAll(context)
        statusPublisher.reset(); mediaSent.clear(); pauseAnnounced = false
        replies.clear(); lan.clear()
        offers = emptyList(); status = if (enabled()) "Sign in again" else "Off"
        access = null; accessAt = 0L
    }
    /** Refresh the free trial notice; failures keep the last answer (an older service has no /v1/access). */
    private fun refreshAccess(token: String, force: Boolean) {
        val now = android.os.SystemClock.elapsedRealtime()
        if (!force && accessAt != 0L && now - accessAt < HostedTrial.REFRESH_MILLIS) return
        val answer = runCatching { transport!!.access(token) }.getOrNull() ?: return
        access = HostedTrial.parse(answer); accessAt = now
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
        // Existing installs predate the UI marker. Restore it only from a
        // verified saved root signature that includes this exact key pair.
        if (!prefs.getBoolean("approval_verified", false) && opened.hasRetainedApproval())
            check(prefs.edit().putBoolean("approval_verified", true).commit())
        session = opened; transport = HostedHttpTransport.create(prefs.getString("origin", "")!!, opened)
        fingerprint = HostedApprovalCodes.deviceFingerprint(opened.enrollment().getValue("device").jsonObject)
        identityUnavailable = false
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
        identityUnavailable = true
        Security.ensureKey()
        val keys = HostedRecipientKeys.forDeployment(context, root.deploymentId, id).create()
        check(prefs.edit().putString("recipient", HostedEnvelope.exportPublic(keys.recipient)).commit())
        val current = HostedSession(root, id, keys, AndroidHostedTrustStore.create(context, root.deploymentId, id))
        session = current; transport = HostedHttpTransport.create(prefs.getString("origin", "")!!, current)
        requestCode = HostedApprovalCodes.request(current)
        fingerprint = HostedApprovalCodes.deviceFingerprint(current.enrollment().getValue("device").jsonObject)
        identityUnavailable = false
        status = "Waiting for root approval"
        lastEnrollmentAttempt = android.os.SystemClock.elapsedRealtime()
        transport!!.submitEnrollment(token)
        offer(token)
        UsageAnalytics.count(context, "hosted_enrolled")
        status = "Waiting for root approval"
    }
    suspend fun freshRequest() = mutex.withLock {
        check(enabled()); val token = HostedAccount.get(context).token()
        val current = try { open() } catch (failure: Exception) {
            identityUnavailable = true; status = "Connection setup needs recovery"; throw failure
        }
        requestCode = HostedApprovalCodes.request(current)
        identityUnavailable = false
        lastEnrollmentAttempt = android.os.SystemClock.elapsedRealtime()
        transport!!.submitEnrollment(token); offer(token)
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
                if (bytes.size > 16384) { clipboardNotice = "This clipboard text is too large to share. Send it as a file."; return false }
                if (bytes.isEmpty() || !cache.claim("text/plain", ClipboardCache.hash(bytes))) return false
                clearClipboardImage(); clipboardNotice = ""
                buildJsonObject { put("type", type); put("text", text); put("sha256", ClipboardCache.hash(bytes)) }
            }
            "notification.upsert", "notification.remove", HostedNotificationFrames.ACTIONS -> if (access.notifications) value else return false
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
        if (!HostedPhoneFrames.mayPublish(type, OrionPermissions.read(context), textsAndCalls(), photosShared()) || type == HostedPhoneFrames.CAPABILITIES
            || !HostedPhoneFrames.fits(value)) return false
        if (type.startsWith("sms.") || type.startsWith("photos.")) return texts.offer(Delivery(target, value, delivered))
        if (type == "call.state") ringing = value["state"] == JsonPrimitive("ringing")
        return calls.offer(Delivery(target, value, delivered)).also { if (it) wake.trySend(Unit) }
    }
    suspend fun step() = mutex.withLock {
        if (!enabled()) { invalidate(); return@withLock }
        if (!prefs.contains("device_id")) { status = "Scan or paste the root code"; return@withLock }
        val epoch = generation
        fun gate() { check(epoch == generation && enabled() && HostedAccount.get(context).signedIn()) }
        // Sync over mobile data is off and the phone is on a metered network: tell
        // the computers once, then make no Cloud requests until that changes.
        val paused = pausedOnMobileData()
        if (!paused && pauseAnnounced) { pauseAnnounced = false; advertised = null; statusPublisher.invalidate() }
        if (paused && pauseAnnounced) { status = "Paused on mobile data"; return@withLock }
        val current = try { open() } catch (_: Exception) { identityUnavailable = true; status = "Connection setup needs recovery"; return@withLock }
        val token = try { HostedAccount.get(context).token() }
        catch (failure: kotlinx.coroutines.CancellationException) { throw failure }
        catch (_: Exception) {
            // A network outage while rotating a token does not sign the owner out
            // or discard subscriptions. Nothing is sent until token() succeeds.
            if (!HostedAccount.get(context).signedIn()) invalidate() else status = "Reconnecting…"
            return@withLock
        }
        // After a refusal, look again each pass so a new subscription clears the notice at once.
        refreshAccess(token, force = status == HostedTrial.PAUSED)
        try { transport!!.refreshTrust(token) } catch (_: Exception) {
            // A transient submit/offer failure must not strand a signed-in phone.
            // Reuse the same pinned identity; never re-enroll a previously approved
            // device or treat an enrollment response as approval.
            val now = android.os.SystemClock.elapsedRealtime()
            if (HostedSetup.retryEnrollment(prefs.getBoolean("approval_verified", false), lastEnrollmentAttempt, now)) {
                lastEnrollmentAttempt = now
                runCatching {
                    gate()
                    requestCode = HostedApprovalCodes.request(current)
                    gate(); transport!!.submitEnrollment(token)
                    gate(); offer(token)
                }
            }
            // A refused account (typically a free trial that ended) is paused, not waiting:
            // nothing local is removed, and subscribing reconnects on a later pass.
            refreshAccess(token, force = true)
            outgoing.clear(); offers = emptyList()
            status = if (HostedTrial.refused(access)) HostedTrial.PAUSED else "Waiting for root approval or renewal"; return@withLock
        }
        gate()
        // Only a successfully verified roster can complete setup. A local ID or an
        // account token is never evidence that this phone has been approved.
        current.currentMembers()
        identityUnavailable = false
        check(prefs.edit().putBoolean("approval_verified", true).commit())
        status = "Connected"
        runCatching { watchMembers(current) }
        members = current.currentMembers().keys - current.deviceId
        subscriptions.keys.retainAll(members) // A revoked computer stops receiving at once.
        SessionOffers.retain(subscribers().keys)
        lan.clear(keep = members)
        RequestPrompts.sync(context)
        // Tell every approved device what this phone offers, on change and every two
        // minutes; computers answer with phone.subscribe. The roster has no device kinds.
        val offered = HostedPhoneFrames.capabilities(OrionPermissions.read(context), textsAndCalls(), photosShared())
        // Phone screen and app list go in their own event, which older computers ignore.
        val screen = HostedPhoneFrames.screenCapabilities(PhoneScreenActivity.offersAllowed(context))
        // Notification buttons and replies, MMS pictures and group replies: their own event too.
        val features = HostedPhoneFrames.features(OrionPermissions.read(context), textsAndCalls())
        if (offered != advertised || screen != advertisedScreen || features != advertisedFeatures || System.currentTimeMillis() - advertisedAt > 120_000) {
            for (member in members) {
                gate(); transport!!.send(member, HostedPhoneFrames.capabilitiesPayload(offered))
                if (screen.isNotEmpty() || advertisedScreen?.isNotEmpty() == true) {
                    gate(); transport!!.send(member, HostedPhoneFrames.screenCapabilitiesPayload(screen))
                }
                if (features.isNotEmpty() || advertisedFeatures?.isNotEmpty() == true) {
                    gate(); transport!!.send(member, HostedPhoneFrames.featuresPayload(features))
                }
            }
            advertised = offered; advertisedScreen = screen; advertisedFeatures = features; advertisedAt = System.currentTimeMillis()
        }
        if (paused) {
            runCatching { syncStatus({ target, payload -> gate(); transport!!.send(target, payload) }, true) }
            outgoing.clear(); texts.clear(); calls.clear(); ringing = false
            pauseAnnounced = true; status = "Paused on mobile data"; return@withLock
        }
        while (true) {
            val payload = outgoing.poll() ?: break
            val type = payload["type"]?.jsonPrimitive?.content
            val access = OrionPermissions.read(context)
            if (type == "clipboard.text" && !access.clipboard || type?.startsWith("notification.") == true && !access.notifications) continue
            // Like clipboard images, text and notifications reach every approved
            // computer, not only the main one: a joined computer is a full peer.
            for (member in members) { gate(); transport!!.send(member, payload) }
        }
        while (true) {
            val (target, payload) = replies.poll() ?: break
            if (target in members) { gate(); transport!!.send(target, payload) }
        }
        syncClipboardImage(current, epoch)
        // Each phone delivery names one computer, which must still be subscribed and approved.
        fun deliver(item: Delivery) {
            val type = item.payload.getValue("type").jsonPrimitive.content
            val permitted = if (type == PhoneStatusFrames.WALLPAPER) statusShared() && "wallpaper" in controlsNow()
                else HostedPhoneFrames.mayPublish(type, OrionPermissions.read(context), textsAndCalls(), photosShared())
            if (item.target !in subscribers() || !permitted) return
            if (type == "photos.item") {
                val uri = android.content.ContentUris.withAppendedId(android.provider.MediaStore.Images.Media.EXTERNAL_CONTENT_URI,
                    item.payload.getValue("id").jsonPrimitive.content.toLong())
                if (runCatching { context.contentResolver.openFileDescriptor(uri, "r")?.use { true } ?: false }.getOrDefault(false).not()) return
            }
            gate(); transport!!.send(item.target, item.payload)
            runCatching(item.delivered)
        }
        while (true) deliver(calls.poll() ?: break)
        syncStatus({ target, payload -> gate(); transport!!.send(target, payload) }, false)
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
                "file.encrypted" -> if (payload["kind"] == JsonPrimitive("clipboard.image")) {
                    try { receiveClipboardImage(current, envelope, payload, epoch, source, id) }
                    catch (failure: kotlinx.coroutines.CancellationException) { throw failure }
                    catch (_: Exception) { clipboardNotice = "A clipboard image could not be received. Ask the sender to copy it again." }
                    finally { current.completeIncoming(id) }
                } else files += id to payload.getValue("name").jsonPrimitive.content.take(255)
                "clipboard.text" -> {
                    check(payload.keys == setOf("type", "text", "sha256"))
                    val text = payload.getValue("text").jsonPrimitive.content
                    val raw = text.toByteArray(Charsets.UTF_8)
                    check(raw.size in 1..16384 && ClipboardCache.hash(raw) == payload.getValue("sha256").jsonPrimitive.content)
                    if (OrionPermissions.read(context).clipboard && receipts.claim("hosted:$id")) {
                        clipboard?.invoke(text) {
                            runCatching { epoch == generation && session === current && enabled() && HostedAccount.get(context).signedIn() &&
                                OrionPermissions.read(context).clipboard && source in current.currentMembers() && cache.claim("text/plain", ClipboardCache.hash(raw)) }.getOrDefault(false)
                        }; UsageAnalytics.count(context, "clipboard_received")
                    }
                }
                "notification.dismiss" -> {
                    // Every approved computer receives notifications, so any of them may dismiss one.
                    check(source in members)
                    check(payload.keys == setOf("type", "key"))
                    val key = payload.getValue("key").jsonPrimitive.content
                    check(Regex("[A-Za-z0-9._:|/+=@-]{1,256}").matches(key))
                    if (OrionPermissions.read(context).notifications && receipts.claim("hosted:$id")) dismiss?.invoke(key)
                }
                // A button, reply or open from any approved computer (all of them receive notifications), at most once.
                in HostedNotificationFrames.COMMANDS -> if (source in members && OrionPermissions.read(context).notifications) {
                    val command = HostedNotificationFrames.command(payload)
                    if (command != null && receipts.claim("hosted:$id")) runCatching { notificationCommand?.invoke(command) }
                }
                // A computer, root or not, asks for texts and calls under its display name.
                HostedPhoneFrames.SUBSCRIBE -> HostedPhoneFrames.subscribe(payload)?.let { name ->
                    if (source in members) subscriptions[source] = name to System.currentTimeMillis()
                }
                // Quick actions: a subscribed computer, a control this phone lists now, and at most once per event.
                in PhoneStatusFrames.COMMAND_CONTROL -> {
                    val command = PhoneStatusFrames.command(payload)
                    if (command != null && PhoneStatusFrames.allowed(type, source, subscribers().keys, controlsNow()) && receipts.claim("hosted:$id")) {
                        if (command == PhoneControlCommand.Status) {
                            // Refresh is rate limited per computer; the status goes out on the next pass.
                            if (statusPublisher.refresh(source, source, System.currentTimeMillis())) mediaSent.remove(source)
                        } else runCatching { control?.invoke(source, command) }
                        wake.trySend(Unit)
                    }
                }
                // A local invitation instead of a QR (shared format: SessionOffer.kt): only from a
                // subscribed computer, shown at most once, and nothing starts until the owner taps,
                // verifies and allows it. Phone screen offers also need the owner's offers switch.
                SessionOffer.TYPE -> runCatching {
                    val offer = SessionOffer.parse(payload)
                    // A file from any approved computer is fetched without a prompt: the owner started
                    // the send on their own device, and it waits in private storage for Save.
                    if (offer.service == "file") {
                        if (source in members && offer.file.mode == "get" && receipts.claim("offer:${offer.id}")) lan.receive(offer, source, deviceName(source))
                        else if (source in members && offer.file.mode == "put") lan.answered(offer.file.request, source, offer)
                    } else if (source in subscribers()) when (offer.service) {
                        "camera" -> if (receipts.claim("offer:${offer.id}") && SessionOffers.put(offer, label(source), source))
                            RequestPrompts.show(context, offer, label(source))
                        "screen" -> if (PhoneScreenActivity.offersAllowed(context) &&
                            receipts.claim("offer:${offer.id}") && SessionOffers.put(offer, label(source), source))
                            RequestPrompts.show(context, offer, label(source))
                    }
                }
                // The same computer says its offer was answered, cancelled or expired: clear the prompt now.
                SessionOffer.CLOSE_TYPE -> if (source in members) SessionOffer.parseClose(payload)?.let { offerId ->
                    if (SessionOffers.close(offerId, source) != null) RequestPrompts.closed(context, offerId)
                    lan.closed(offerId, source)
                }
                // The computer cannot take this phone's direct upload: Saiph Cloud, or say why.
                LanFileFormat.REFUSE -> if (source in members) LanFileFormat.parseRefuse(payload)?.let { (id, reason) -> lan.answered(id, source, reason) }
                // App lists go only to the requesting computer, while the owner allows them.
                in HostedPhoneFrames.SCREEN_COMMANDS -> if (HostedPhoneFrames.screenAllowed(type, source, subscribers().keys,
                        PhoneScreenActivity.offersAllowed(context))) {
                    if (HostedPhoneFrames.appsRequest(payload))
                        for (page in HostedPhoneFrames.appsPages(ScreenProtocol.appRows(PhoneApps.list(context)))) { gate(); transport!!.send(source, page) }
                    // Small app icons for the computer's Apps grid, bounded and rate limited per computer.
                    else AppIcons.request(payload)?.takeIf { AppIcons.allow(source) }?.let { wants ->
                        for (event in AppIcons.answer(context, wants)) { gate(); transport!!.send(source, event) }
                    }
                }
                // Decryption proves origin only. Texts and calls need a subscribed roster member
                // as sender, the owner's switch and the Android permission, checked at execution.
                in HostedPhoneFrames.COMMAND_CAPABILITY -> {
                    val command = HostedPhoneFrames.command(payload)
                    // Texts and calls run at most once; reads (sync, open, search, history) may repeat.
                    if (command != null && HostedPhoneFrames.allowed(type, source, subscribers().keys, OrionPermissions.read(context), textsAndCalls(), photosShared())
                        && (!HostedPhoneFrames.isEffect(command) || receipts.claim("hosted:$id"))) runCatching { phone?.invoke(id, source, command) }
                }
            }
            if (payload["type"] != JsonPrimitive("file.encrypted")) current.completeIncoming(id)
        }
        gate(); offers = files
    }
    /** Share-sheet targets come from the current signed roster and live computer subscriptions. */
    suspend fun shareTargets(): Map<String, String> = mutex.withLock {
        check(enabled() && HostedAccount.get(context).signedIn() && !OrionPause.paused(context))
        val current = open()
        val approved = current.currentMembers().keys - current.deviceId
        subscribers().filterKeys { it in approved }
    }
    /**
     * One file to a computer: directly over the local network when both are on it (any size),
     * otherwise, or when the computer cannot connect, with Saiph Cloud up to its limit.
     */
    suspend fun sendFile(uri: Uri, target: String? = null): String {
        var name = "shared-file"; var size: Long? = null
        val recipient = mutex.withLock {
            check(enabled() && HostedAccount.get(context).signedIn()); val current = open()
            val recipient = target ?: current.root.deviceId
            check(!OrionPause.paused(context) && recipient != current.deviceId && recipient in current.currentMembers())
            if (target != null) check(recipient in subscribers())
            context.contentResolver.query(uri, arrayOf(android.provider.OpenableColumns.DISPLAY_NAME, android.provider.OpenableColumns.SIZE), null, null, null)?.use {
                if (it.moveToFirst()) { name = it.getString(0) ?: name; if (!it.isNull(1)) size = it.getLong(1) }
            }
            recipient
        }
        val known = size
        if (known != null && LanFileFormat.onPrivateNetwork()) {
            val direct = LanFileFormat.safeName(name)
            when (val outcome = lan.send(recipient, deviceName(recipient), direct, known) { context.contentResolver.openInputStream(uri)!! }) {
                LanTransfers.Outcome.Sent -> { UsageAnalytics.count(context, "hosted_file_send"); return direct }
                is LanTransfers.Outcome.Refused -> throw TransferRefused(HostedTransferText.refused(outcome.reason, deviceName(recipient)))
                is LanTransfers.Outcome.Failed -> throw TransferRefused(HostedTransferText.failed(outcome.code, deviceName(recipient)))
                LanTransfers.Outcome.Unreachable -> if (known > HostedTransferText.MAX_PLAINTEXT)
                    throw TransferRefused(HostedTransferText.needsNetwork(known, deviceName(recipient)))
            }
        } else if (known != null && known > HostedTransferText.MAX_PLAINTEXT) throw TransferRefused(HostedTransferText.noNetwork(known))
        return sendWithCloud(uri, target, recipient, name, size)
    }

    private suspend fun sendWithCloud(uri: Uri, target: String?, recipient: String, name: String, size: Long?) = mutex.withLock {
        check(enabled() && HostedAccount.get(context).signedIn()); val current = open()
        fun authorize() {
            check(enabled() && HostedAccount.get(context).signedIn() && !OrionPause.paused(context) && session === current)
            check(recipient != current.deviceId && recipient in current.currentMembers())
            if (target != null) check(recipient in subscribers())
        }
        authorize()
        // Refuse before reading or encrypting anything, with the size the owner can act on.
        HostedTransferText.checkSize(size)
        context.contentResolver.openInputStream(uri)!!.use { input ->
            HostedAttachments.send(current, transport!!, input, name, "application/octet-stream", recipient, authorize = ::authorize)
        }
        UsageAnalytics.count(context, "hosted_file_send")
        name
    }
    fun deviceName(device: String): String = label(device).ifBlank { "your computer" }
    suspend fun sendPhoto(request: String, target: String, photo: String) = mutex.withLock {
        check(enabled() && HostedAccount.get(context).signedIn() && photosShared() && OrionPermissions.read(context).photos)
        val current = open(); current.currentMembers()
        check(target in subscribers())
        val uri = android.content.ContentUris.withAppendedId(android.provider.MediaStore.Images.Media.EXTERNAL_CONTENT_URI, photo.toLong())
        val name = context.contentResolver.query(uri, arrayOf(android.provider.MediaStore.Images.Media.DISPLAY_NAME), null, null, null)
            ?.use { if (it.moveToFirst()) it.getString(0) else null } ?: "Photo.jpg"
        context.contentResolver.openInputStream(uri)!!.use { input ->
            HostedAttachments.send(current, transport!!, input, name.replace(Regex("[^A-Za-z0-9._ -]"), "_").take(180).trim(' ', '.').ifEmpty { "Photo.jpg" },
                context.contentResolver.getType(uri) ?: "image/jpeg", target, photo, request) {
                check(enabled() && HostedAccount.get(context).signedIn() && photosShared() && OrionPermissions.read(context).photos && target in subscribers())
                current.currentMembers()
                check(context.contentResolver.openFileDescriptor(uri, "r")?.use { true } == true)
            }
        }
    }
    /** One MMS part for the computer that asked, as a sealed attachment answering its request. */
    suspend fun sendSmsPart(request: String, target: String, part: HostedPhoneCommand.SmsPart) = mutex.withLock {
        fun authorize() {
            check(enabled() && HostedAccount.get(context).signedIn() && textsAndCalls() && OrionPermissions.read(context).sms && target in subscribers())
        }
        authorize()
        val current = open(); current.currentMembers()
        val found = MmsParts.find(context, part.thread, part.message, part.part)
        context.contentResolver.openInputStream(found.uri)!!.use { input ->
            HostedAttachments.send(current, transport!!, input, MmsParts.safeName(found.name, part.part), MmsParts.safeMime(found.mime), target,
                wrap = HostedPhoneFrames.smsAttachmentOriginal(part.thread, part.message, part.part, request)) {
                authorize(); current.currentMembers()
            }
        }
    }
    suspend fun saveFile(id: String, uri: Uri) = deliver(id) { verified, _ ->
        context.contentResolver.openOutputStream(uri, "w")!!.use { output -> verified.inputStream().use { it.copyTo(output) } }
    }
    /** One tap: Downloads → Saiph through MediaStore (Android 10 and later), never overwriting a file. */
    @androidx.annotation.RequiresApi(29)
    suspend fun saveToDownloads(id: String): String {
        var saved = ""
        deliver(id) { verified, name ->
            val resolver = context.contentResolver
            val values = android.content.ContentValues().apply {
                put(android.provider.MediaStore.MediaColumns.DISPLAY_NAME, name)
                put(android.provider.MediaStore.MediaColumns.RELATIVE_PATH, android.os.Environment.DIRECTORY_DOWNLOADS + "/" + HostedTransferText.FOLDER)
                put(android.provider.MediaStore.MediaColumns.IS_PENDING, 1)
            }
            val uri = resolver.insert(android.provider.MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)!!
            try {
                resolver.openOutputStream(uri, "w")!!.use { output -> verified.inputStream().use { it.copyTo(output) } }
                resolver.update(uri, android.content.ContentValues().apply { put(android.provider.MediaStore.MediaColumns.IS_PENDING, 0) }, null, null)
                // MediaStore renames a clash, for example "photo (1).jpg".
                saved = resolver.query(uri, arrayOf(android.provider.MediaStore.MediaColumns.DISPLAY_NAME), null, null, null)
                    ?.use { if (it.moveToFirst()) it.getString(0) else null } ?: name
            } catch (failure: Exception) { resolver.delete(uri, null, null); throw failure }
        }
        return saved
    }
    /** Files received over the local network, as (ID, name, state, line) rows for the daily screen. */
    internal fun lanReceived(): List<LanTransfers.Incoming> = lan.incoming.values.filter { it.state != "waiting" }.sortedBy { it.name }
    fun dismissReceived(id: String) = lan.dismiss(id.removePrefix("lan:"))

    private suspend fun deliver(id: String, write: (File, String) -> Unit) {
        if (id.startsWith("lan:")) {
            // Already verified in private storage: no Saiph Cloud needed to save it.
            lan.deliver(id.removePrefix("lan:"), write)
            UsageAnalytics.count(context, "hosted_file_save")
            return
        }
        deliverFromCloud(id, write)
    }

    private suspend fun deliverFromCloud(id: String, write: (File, String) -> Unit) = mutex.withLock {
        check(enabled() && HostedAccount.get(context).signedIn()); val current = open()
        val envelope = current.pendingIncoming().first { it.getValue("header").jsonObject.getValue("id").jsonPrimitive.content == id }
        val name = offers.firstOrNull { it.first == id }?.second ?: "Saiph file"
        // Verify the complete encrypted file privately before opening the user's destination.
        val verified = HostedAttachments.receive(current, transport!!, envelope, context.noBackupFilesDir)
        try {
            check(receipts.claim("hosted:$id")) { "This offer was already saved. Check your files." }
            write(verified, name)
            current.completeIncoming(id)
            offers = offers.filterNot { it.first == id }
            UsageAnalytics.count(context, "hosted_file_save")
        } finally { verified.delete() }
    }
    /** Explicitly abandon a failed attempt, retaining its files and the account sign-in. */
    suspend fun restartSetup() = mutex.withLock {
        check(setupStage() == HostedSetup.Stage.RECOVERY)
        HostedAccount.get(context).cancel()
        invalidate()
        clearIdentityIntent()
        status = if (enabled()) "Scan your computer's QR code" else "Off"
    }
    private fun clearIdentityIntent() {
        check(prefs.edit().remove("device_id").remove("root").remove("recipient").remove("seen_members").remove("texts_and_calls").remove("photos_shared").remove("approval_verified")
            .remove("sharing_setup_step").remove("sharing_setup_complete").commit())
        identityUnavailable = false; requestCode = ""; fingerprint = ""; lastEnrollmentAttempt = 0L
        HostedSmsKnown.clearAll(context)
    }
    fun retire() {
        check(!enabled()); HostedAccount.get(context).signOut(); invalidate()
        // Keystore keys and encrypted trust history stay available for explicit
        // recovery. A newly enrolled member gets a fresh unique device ID.
        clearIdentityIntent()
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
