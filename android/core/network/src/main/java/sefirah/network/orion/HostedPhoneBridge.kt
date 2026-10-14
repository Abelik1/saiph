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
import java.util.UUID
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Conversations the root computer has received over Saiph Hosted, as thread
 * checksums only. Recorded after a successful send, so an interrupted sync
 * resumes with the threads that are still missing.
 */
class HostedSmsKnown(context: Context) {
    private val prefs = context.getSharedPreferences("orion_hosted_sms", Context.MODE_PRIVATE)
    private fun read(): MutableMap<Long, Long> {
        val saved = runCatching { JSONObject(prefs.getString("threads", "{}")!!) }.getOrDefault(JSONObject())
        return saved.keys().asSequence().mapNotNull { key -> key.toLongOrNull()?.let { it to saved.optLong(key) } }.toMap(LinkedHashMap())
    }
    @Synchronized fun threads(): List<ThreadInfo> = read().map { (thread, checksum) -> ThreadInfo(thread, checksum) }
    @Synchronized fun sent(message: SocketMessage) {
        val threads = read()
        when (message) {
            is ConversationInfo -> threads[message.threadId] = message.checksum
            // Only threads the computer already lists; a new thread arrives as ConversationInfo.
            is MessageList -> message.checksum?.let { if (message.threadId in threads) threads[message.threadId] = it }
            is MessageIndex -> if (message.threadId in threads) threads[message.threadId] = message.checksum
            is RemoveConversation -> threads.remove(message.threadId)
            else -> return
        }
        val kept = JSONObject()
        threads.entries.toList().takeLast(2000).forEach { (thread, checksum) -> kept.put(thread.toString(), checksum) }
        prefs.edit().putString("threads", kept.toString()).apply()
    }
    @Synchronized fun clear() { if (prefs.contains("threads")) prefs.edit().remove("threads").apply() }
}

/**
 * Runs the retained SMS and call features for Saiph Hosted and carries out the
 * root computer's phone actions. The caller has already checked that the action
 * came from the root, that the owner's "Texts and calls" switch is on and that
 * the matching Android permission is granted (`HostedPhoneFrames.allowed`).
 */
@Singleton
class HostedPhoneBridge @Inject constructor(private val context: Context, private val sms: SmsFeature,
                                            private val calls: CallStateFeature) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val mutex = Mutex()
    private val known = HostedSmsKnown(context)
    private var smsEnabled = false
    private var callsEnabled = false
    private var lastSync = 0L
    private var contactCache: Pair<Long, List<ContactInfo>>? = null

    /** Match the features to the switch and permissions; resume an unfinished conversation sync. */
    suspend fun refresh(textsAndCalls: Boolean, connected: Boolean) = mutex.withLock {
        val access = OrionPermissions.read(context)
        val messages = textsAndCalls && access.sms
        if (messages && !smsEnabled) { sms.enable(""); smsEnabled = true; lastSync = 0 }
        if (!messages && smsEnabled) { sms.disable(""); smsEnabled = false }
        val call = textsAndCalls && access.calls
        if (call && !callsEnabled) { calls.enable(""); callsEnabled = true }
        if (!call && callsEnabled) { calls.disable(""); callsEnabled = false }
        // Turning texts off forgets what was sent, so turning them on again resends the list.
        if (!messages) known.clear()
        if (smsEnabled && connected && System.currentTimeMillis() - lastSync > 60_000) {
            lastSync = System.currentTimeMillis()
            sms.handleConversationsRequest("", ConversationsRequest(known.threads()))
        }
    }

    suspend fun stop() = mutex.withLock {
        if (smsEnabled) sms.disable(""); if (callsEnabled) calls.disable("")
        smsEnabled = false; callsEnabled = false; contactCache = null
    }

    /** At most once per event: the runtime claims a receipt before calling this. */
    fun execute(id: String, command: HostedPhoneCommand, answer: (String, JsonObject) -> Boolean) {
        val unique = UUID.fromString(id).leastSignificantBits and Long.MAX_VALUE
        when (command) {
            HostedPhoneCommand.SmsSync -> {
                known.clear()
                scope.launch { mutex.withLock { if (smsEnabled) { lastSync = System.currentTimeMillis(); sms.handleConversationsRequest("", ConversationsRequest()) } } }
            }
            is HostedPhoneCommand.SmsOpen -> if (smsEnabled) sms.handleMessagesRequest("", MessagesRequest(command.thread))
            is HostedPhoneCommand.SmsSend -> {
                val recipients = SMSHelper.getThreadRecipients(context, command.thread)
                // One-to-one replies only: group replies need MMS and stay on the phone.
                require(recipients.size == 1)
                val subscription = SMSHelper.getNewestMessageRef(context, command.thread)
                    ?.let { SMSHelper.getMessagesByRefs(context, listOf(it)).firstOrNull()?.subscriptionID } ?: 0
                sms.sendTextMessage("", TextMessage(uniqueId = unique, addresses = recipients, body = command.text, subscriptionId = subscription))
            }
            is HostedPhoneCommand.SmsCompose ->
                sms.sendTextMessage("", TextMessage(uniqueId = unique, addresses = listOf(command.address), body = command.text))
            is HostedPhoneCommand.Call -> {
                require(OrionPhoneFeatures.hasPermission(context, Manifest.permission.ANSWER_PHONE_CALLS))
                @Suppress("DEPRECATION")
                if (context.getSystemService(TelephonyManager::class.java).callState == TelephonyManager.CALL_STATE_RINGING) {
                    val telecom = context.getSystemService(TelecomManager::class.java)
                    @Suppress("DEPRECATION")
                    if (command.answer) telecom.acceptRingingCall() else telecom.endCall()
                }
            }
            is HostedPhoneCommand.Dial -> {
                require(PhoneFeatureFrames.dialable(command.number) && OrionPhoneFeatures.hasPermission(context, Manifest.permission.CALL_PHONE))
                // Telecom shows the in-call screen; audio stays on the phone.
                context.getSystemService(TelecomManager::class.java).placeCall(Uri.fromParts("tel", command.number, null), Bundle())
            }
            is HostedPhoneCommand.ContactsSearch -> {
                val cached = contactCache?.takeIf { System.currentTimeMillis() - it.first < 60_000 }?.second
                val all = cached ?: ContactsHelper().getAllContacts(context).also { contactCache = System.currentTimeMillis() to it }
                answer("contacts.results", HostedPhoneFrames.contacts(command.query, all))
            }
            HostedPhoneCommand.CallsLog -> answer("calls.log", HostedPhoneFrames.callLog(CallLogHelper.getCallLogs(context)))
        }
    }
}
