// SPDX-License-Identifier: GPL-3.0-only
package sefirah.network.orion

import android.Manifest
import android.content.Context
import android.net.Uri
import android.os.Bundle
import android.telecom.TelecomManager
import android.telephony.TelephonyManager
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.json.JsonObject
import org.json.JSONObject
import sefirah.communication.call.CallLogHelper
import sefirah.communication.call.CallStateFeature
import sefirah.communication.sms.SMSHelper
import sefirah.communication.sms.SmsFeature
import sefirah.communication.utils.ContactsHelper
import sefirah.domain.model.*
import sefirah.media.PlaybackFeature
import java.util.UUID
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Conversations one subscribed computer has received over Saiph Hosted, as
 * thread checksums only. Recorded after a successful send, so an interrupted
 * sync resumes with the threads that computer is still missing.
 */
class HostedSmsKnown(context: Context, private val device: String) {
    private val prefs = context.getSharedPreferences("orion_hosted_sms", Context.MODE_PRIVATE)
    private val key = "threads:$device"
    private fun read(): MutableMap<Long, Long> {
        val saved = runCatching { JSONObject(prefs.getString(key, "{}")!!) }.getOrDefault(JSONObject())
        return saved.keys().asSequence().mapNotNull { name -> name.toLongOrNull()?.let { it to saved.optLong(name) } }.toMap(LinkedHashMap())
    }
    fun threads(): List<ThreadInfo> = synchronized(lock) { read().map { (thread, checksum) -> ThreadInfo(thread, checksum) } }
    fun sent(message: SocketMessage) = synchronized(lock) {
        val threads = read()
        when (message) {
            is ConversationInfo -> threads[message.threadId] = message.checksum
            // Only threads the computer already lists; a new thread arrives as ConversationInfo.
            is MessageList -> message.checksum?.let { if (message.threadId in threads) threads[message.threadId] = it }
            is MessageIndex -> if (message.threadId in threads) threads[message.threadId] = message.checksum
            is RemoveConversation -> threads.remove(message.threadId)
            else -> return@synchronized
        }
        val kept = JSONObject()
        threads.entries.toList().takeLast(2000).forEach { (thread, checksum) -> kept.put(thread.toString(), checksum) }
        prefs.edit().putString(key, kept.toString()).apply()
    }
    fun clear() = synchronized(lock) { if (prefs.contains(key)) prefs.edit().remove(key).apply() }

    companion object {
        private val lock = Any()
        /** Forget every computer's progress, so turning texts on again resends the list. */
        fun clearAll(context: Context) = synchronized(lock) {
            val prefs = context.getSharedPreferences("orion_hosted_sms", Context.MODE_PRIVATE)
            if (prefs.all.isNotEmpty()) prefs.edit().clear().apply()
        }
    }
}

/**
 * Runs the retained SMS and call features for Saiph Hosted, once per subscribed
 * computer, and carries out phone actions. The caller has already checked that
 * the action came from a current subscribed roster member, that the owner's
 * "Texts and calls" switch is on and that the matching Android permission is
 * granted (`HostedPhoneFrames.allowed`). Calls are settled by [HostedCallRace].
 */
@Singleton
class HostedPhoneBridge @Inject constructor(private val context: Context, private val sms: SmsFeature,
                                            private val calls: CallStateFeature, private val playback: PlaybackFeature) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val mutex = Mutex()
    private val race = HostedCallRace.shared
    private val smsDevices = mutableSetOf<String>()
    private val callDevices = mutableSetOf<String>()
    private val lastSync = mutableMapOf<String, Long>()
    private var contactCache: Pair<Long, List<ContactInfo>>? = null
    private var mediaEnabled = false

    /**
     * Match the features to the switches, permissions and subscribers; resume
     * unfinished syncs. Media sessions are read through notification access, only
     * while [media] (the owner's status switch) is on and a computer subscribed.
     */
    suspend fun refresh(textsAndCalls: Boolean, connected: Boolean, subscribers: Set<String>, media: Boolean = false) = mutex.withLock {
        val access = OrionPermissions.read(context)
        val playing = media && access.notifications && subscribers.isNotEmpty()
        if (playing && !mediaEnabled) { playback.enable(""); mediaEnabled = true }
        if (!playing && mediaEnabled) { playback.disable(""); mediaEnabled = false; OrionPhoneFeatures.media.retain(emptySet()); HostedFeatureBridge.mediaChanged() }
        if (mediaEnabled) OrionPhoneFeatures.media.retain(playback.getActivePackageNames())?.let { HostedFeatureBridge.mediaChanged() }
        val messages = if (textsAndCalls && access.sms) subscribers else emptySet()
        (smsDevices - messages).forEach { sms.disable(it); smsDevices.remove(it); lastSync.remove(it) }
        (messages - smsDevices).forEach { sms.enable(it); smsDevices.add(it) }
        val call = if (textsAndCalls && access.calls) subscribers else emptySet()
        (callDevices - call).forEach { calls.disable(it); callDevices.remove(it) }
        (call - callDevices).forEach { calls.enable(it); callDevices.add(it) }
        // Turning texts off forgets what was sent, so turning them on again resends the list.
        if (!textsAndCalls || !access.sms) HostedSmsKnown.clearAll(context)
        if (!connected) return@withLock
        val now = System.currentTimeMillis()
        for (device in smsDevices) if (now - (lastSync[device] ?: 0L) > 60_000) {
            lastSync[device] = now
            sms.handleConversationsRequest(device, ConversationsRequest(HostedSmsKnown(context, device).threads()))
        }
    }

    suspend fun stop() = mutex.withLock {
        smsDevices.forEach { sms.disable(it) }; callDevices.forEach { calls.disable(it) }
        if (mediaEnabled) { playback.disable(""); mediaEnabled = false; OrionPhoneFeatures.media.retain(emptySet()) }
        smsDevices.clear(); callDevices.clear(); lastSync.clear(); contactCache = null
    }

    @Suppress("DEPRECATION")
    private fun phoneCallState(): Int? = runCatching { context.getSystemService(TelephonyManager::class.java).callState }.getOrNull()

    /**
     * At most once per event for texts, calls and dials: the runtime claims a
     * receipt first. [send] reaches one computer; [everyone] lists the subscribers.
     */
    fun execute(id: String, source: String, label: String, command: HostedPhoneCommand,
                send: (String, JsonObject) -> Boolean, everyone: () -> Collection<String>) {
        val unique = UUID.fromString(id).leastSignificantBits and Long.MAX_VALUE
        when (command) {
            is HostedPhoneCommand.PhotoRequest, is HostedPhoneCommand.SmsPart -> Unit // Sealed attachments: sent by the app's runtime.
            HostedPhoneCommand.SmsSync -> {
                // The full list goes only to the computer that asked.
                HostedSmsKnown(context, source).clear()
                scope.launch { mutex.withLock { if (source in smsDevices) { lastSync[source] = System.currentTimeMillis(); sms.handleConversationsRequest(source, ConversationsRequest()) } } }
            }
            is HostedPhoneCommand.SmsOpen -> if (source in smsDevices) sms.handleMessagesRequest(source, MessagesRequest(command.thread))
            is HostedPhoneCommand.SmsSend -> {
                val recipients = SMSHelper.getThreadRecipients(context, command.thread)
                // Group replies (feature "sms-group") go out as MMS through upstream's group setting, as on the Hub.
                require(recipients.size in 1..10)
                val subscription = SMSHelper.getNewestMessageRef(context, command.thread)
                    ?.let { SMSHelper.getMessagesByRefs(context, listOf(it)).firstOrNull()?.subscriptionID } ?: 0
                sms.sendTextMessage("", TextMessage(uniqueId = unique, addresses = recipients, body = command.text, subscriptionId = subscription))
            }
            is HostedPhoneCommand.SmsCompose ->
                sms.sendTextMessage("", TextMessage(uniqueId = unique, addresses = listOf(command.address), body = command.text))
            is HostedPhoneCommand.Call -> {
                require(OrionPhoneFeatures.hasPermission(context, Manifest.permission.ANSWER_PHONE_CALLS))
                when (val outcome = race.claimCall(label, command.answer, phoneCallState() == TelephonyManager.CALL_STATE_RINGING)) {
                    HostedCallRace.Won -> {
                        val telecom = context.getSystemService(TelecomManager::class.java)
                        @Suppress("DEPRECATION")
                        if (command.answer) telecom.acceptRingingCall() else telecom.endCall()
                        // Every computer stops ringing now, before Android reports the new state.
                        val handled = HostedPhoneFrames.callHandled(command.answer, label)
                        everyone().forEach { send(it, handled) }
                    }
                    is HostedCallRace.Refused -> send(source, HostedPhoneFrames.callRefused(if (command.answer) "answer" else "reject", outcome))
                }
            }
            is HostedPhoneCommand.Dial -> {
                require(PhoneFeatureFrames.dialable(command.number) && OrionPhoneFeatures.hasPermission(context, Manifest.permission.CALL_PHONE))
                val state = phoneCallState()
                when (val outcome = race.claimDial(state != null && state != TelephonyManager.CALL_STATE_IDLE)) {
                    // Telecom shows the in-call screen; audio stays on the phone.
                    HostedCallRace.Won -> context.getSystemService(TelecomManager::class.java).placeCall(Uri.fromParts("tel", command.number, null), Bundle())
                    is HostedCallRace.Refused -> send(source, HostedPhoneFrames.callRefused("dial", outcome))
                }
            }
            is HostedPhoneCommand.ContactsSearch -> {
                val cached = contactCache?.takeIf { System.currentTimeMillis() - it.first < 60_000 }?.second
                val all = cached ?: ContactsHelper().getAllContacts(context).also { contactCache = System.currentTimeMillis() to it }
                send(source, HostedPhoneFrames.contacts(command.query, all))
            }
            HostedPhoneCommand.CallsLog -> send(source, HostedPhoneFrames.callLog(CallLogHelper.getCallLogs(context)))
        }
    }

    /**
     * One quick action from a subscribed computer. The runtime has checked the
     * sender and that the control is listed in this phone's current status;
     * Android permissions are checked again here. [answer] reaches the sender only.
     */
    fun control(command: PhoneControlCommand, answer: (JsonObject) -> Boolean, setMobileData: (Boolean) -> Unit) {
        if (PhoneQuickControls.apply(context, command)) return // Ring, ringer, Do Not Disturb, hotspot: shared with the Hub.
        when (command) {
            is PhoneControlCommand.Media -> {
                check(mediaEnabled && command.source in playback.getActivePackageNames())
                val type = when (command.action) { "play" -> MediaActionType.Play; "pause" -> MediaActionType.Pause; "next" -> MediaActionType.Next; else -> MediaActionType.Previous }
                scope.launch { playback.handlePlaybackAction("", MediaAction(type, command.source, null)) }
            }
            PhoneControlCommand.Wallpaper -> answer(PhoneStatusFrames.wallpaper(PhoneQuickControls.wallpaper(context)))
            is PhoneControlCommand.MobileData -> setMobileData(command.allowed)
            else -> Unit // Status: the runtime resends it itself.
        }
    }
}
