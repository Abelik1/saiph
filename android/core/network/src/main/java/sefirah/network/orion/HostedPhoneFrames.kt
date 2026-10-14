// SPDX-License-Identifier: GPL-3.0-only
package sefirah.network.orion

import kotlinx.serialization.json.*
import sefirah.domain.model.*

/** A phone action from the root computer, after exact-shape validation. */
sealed interface HostedPhoneCommand {
    data object SmsSync : HostedPhoneCommand
    data class SmsOpen(val thread: Long) : HostedPhoneCommand
    data class SmsSend(val thread: Long, val text: String) : HostedPhoneCommand
    data class SmsCompose(val address: String, val text: String) : HostedPhoneCommand
    data class Call(val answer: Boolean) : HostedPhoneCommand
    data class Dial(val number: String) : HostedPhoneCommand
    data class ContactsSearch(val query: String) : HostedPhoneCommand
    data object CallsLog : HostedPhoneCommand
}

/**
 * Saiph Hosted texts and calls, carried inside sealed envelopes between the phone
 * and every approved computer that subscribed with `phone.subscribe`. Pure codec
 * and policy; the desktop's `hosted_features.py` applies the same shapes and limits.
 *
 * Decryption proves which approved device sent an envelope, not that it may act.
 * Phone actions are accepted only from a current roster member that subscribed in
 * the last ten minutes, only while the owner's "Texts and calls" switch for Hosted
 * is on, and only with the matching Android permission. Phone data is published
 * under the same switch and permissions. Calls are first come, first served (see
 * [HostedCallRace]). MMS pictures, group replies and call audio are not part of Hosted.
 */
object HostedPhoneFrames {
    /** Below the sealed 24,000-byte plaintext limit, leaving room for the signature. */
    const val MAX_PAYLOAD_BYTES = 20_000
    private const val MAX_SAFE = 9_007_199_254_740_991L
    private const val MAX_TIMESTAMP = 253_402_300_799_999L
    const val CAPABILITIES = "phone.capabilities"
    const val SUBSCRIBE = "phone.subscribe"
    /** A subscription lasts this long; computers renew it with each capabilities heartbeat. */
    const val SUBSCRIPTION_MILLIS = 600_000L
    val COMMAND_CAPABILITY = mapOf("sms.sync" to "sms", "sms.open" to "sms", "sms.send" to "sms", "sms.compose" to "sms",
        "call.command" to "call-control", "call.dial" to "call-dial", "contacts.search" to "contacts", "calls.log.request" to "call-log")
    val DATA_CAPABILITY = mapOf("sms.thread" to "sms", "sms.messages" to "sms", "sms.remove" to "sms", "sms.index" to "sms",
        "call.state" to "calls", "call.handled" to "calls", "contacts.results" to "contacts", "calls.log" to "call-log")
    /** Sent only to the computer whose answer, decline or dial was overtaken. */
    const val REFUSED = "call.refused"

    /** "files" is the existing encrypted file offer; the rest need the owner's switch. */
    fun capabilities(access: FeatureAccess, textsAndCalls: Boolean): List<String> = buildList {
        add("files")
        if (!textsAndCalls) return@buildList
        if (access.sms) add("sms")
        if (access.calls) add("calls")
        if (access.calls && access.callControl) add("call-control")
        if (access.callDial) add("call-dial")
        if (access.contacts) add("contacts")
        if (access.callLog) add("call-log")
    }

    fun capabilitiesPayload(names: List<String>) = buildJsonObject {
        put("type", CAPABILITIES); put("capabilities", JsonArray(names.map(::JsonPrimitive)))
    }

    /** Publication gate, rechecked when queued and again just before sending. */
    fun mayPublish(type: String, access: FeatureAccess, textsAndCalls: Boolean): Boolean {
        val offered = capabilities(access, textsAndCalls)
        return type == CAPABILITIES || (type == REFUSED && ("call-control" in offered || "call-dial" in offered)) ||
            DATA_CAPABILITY[type]?.let { it in offered } == true
    }

    /** Any subscribed approved computer may cause a phone action, and only one the owner allowed. */
    fun allowed(type: String, source: String, subscribers: Set<String>, access: FeatureAccess, textsAndCalls: Boolean): Boolean {
        val capability = COMMAND_CAPABILITY[type] ?: return false
        return source in subscribers && capability in capabilities(access, textsAndCalls)
    }

    /** A computer's display name, one printable line of up to 40 characters; null if malformed. */
    fun subscribe(payload: JsonObject): String? = runCatching {
        require(payload.keys == setOf("type", "label") && text(payload, "type") == SUBSCRIBE)
        text(payload, "label").takeIf { label ->
            label.isNotBlank() && label.codePointCount(0, label.length) <= 40 && wellFormed(label) && label.none { it.code < 32 || it.code == 127 }
        }
    }.getOrNull()

    /** Every computer stops ringing at once and learns which computer won. */
    fun callHandled(answer: Boolean, by: String) = buildJsonObject {
        put("type", "call.handled"); put("operation", if (answer) "answer" else "reject"); put("by", clean(by, 40))
    }

    /** Why the requester's answer, decline or dial was not carried out. */
    fun callRefused(request: String, refusal: HostedCallRace.Refused) = buildJsonObject {
        require(request in setOf("answer", "reject", "dial"))
        put("type", REFUSED); put("request", request); put("reason", refusal.reason)
        put("handled", refusal.handled); put("by", clean(refusal.by, 40))
    }

    /** Actions with an effect outside Saiph; each runs at most once per event. */
    fun isEffect(command: HostedPhoneCommand) = command is HostedPhoneCommand.SmsSend || command is HostedPhoneCommand.SmsCompose ||
        command is HostedPhoneCommand.Call || command is HostedPhoneCommand.Dial

    /** Well-formed UTF-16 of at most [max] units: lone surrogates become U+FFFD, pairs are never split. */
    fun clean(value: String, max: Int): String {
        val out = StringBuilder(minOf(value.length, max))
        var index = 0
        while (index < value.length) {
            val c = value[index]
            if (Character.isHighSurrogate(c) && index + 1 < value.length && Character.isLowSurrogate(value[index + 1])) {
                if (out.length + 2 > max) break
                out.append(c).append(value[index + 1]); index += 2; continue
            }
            if (out.length + 1 > max) break
            out.append(if (Character.isSurrogate(c)) '�' else c); index++
        }
        return out.toString()
    }

    /** Numbers and sender names: no control characters, never empty. */
    private fun address(value: String, max: Int = 120) = clean(value.filter { it.code >= 32 && it.code != 127 }, max)
    private fun addresses(values: List<String>) = JsonArray(values.map { address(it) }.filter { it.isNotEmpty() }.take(10).map(::JsonPrimitive))
    private fun id(value: Long) = value.coerceIn(0, MAX_SAFE)
    private fun time(value: Long) = value.coerceIn(0, MAX_TIMESTAMP)

    fun fits(payload: JsonObject): Boolean = runCatching { HostedEnvelope.canonical(payload).size <= MAX_PAYLOAD_BYTES }.getOrDefault(false)

    private fun message(m: TextMessage, bodyLimit: Int) = buildJsonObject {
        put("id", id(m.uniqueId)); put("addresses", addresses(m.addresses)); put("body", clean(m.body, bodyLimit))
        put("timestamp", time(m.timestamp)); put("direction", if (m.messageType == 1) "incoming" else "outgoing")
        put("subscription", m.subscriptionId.coerceAtLeast(-1))
    }

    /** Long texts made of escaped characters are shortened until one event holds them. */
    private fun fitted(build: (Int) -> JsonObject): JsonObject? {
        var limit = 4096
        while (limit >= 64) {
            val payload = build(limit)
            if (fits(payload)) return payload
            limit /= 2
        }
        return null
    }

    fun carries(value: SocketMessage) = value is ConversationInfo || value is MessageList || value is RemoveConversation ||
        value is MessageIndex || value is CallInfo

    /** Phone data for a subscribed computer; null for messages that are not texts or calls. */
    fun encode(value: SocketMessage): List<JsonObject>? = when (value) {
        is ConversationInfo -> listOfNotNull(fitted { limit -> buildJsonObject {
            put("type", "sms.thread"); put("thread", id(value.threadId)); put("recipients", addresses(value.recipients))
            put("message", message(value.message, limit))
        } })
        // One message per event: each fits the sealed limit even when full of emoji.
        is MessageList -> value.messages.take(10).mapNotNull { m -> fitted { limit -> buildJsonObject {
            put("type", "sms.messages"); put("thread", id(value.threadId)); put("messages", JsonArray(listOf(message(m, limit))))
        } } }
        is RemoveConversation -> listOf(buildJsonObject { put("type", "sms.remove"); put("thread", id(value.threadId)) })
        // Newest message IDs; the computer keeps only recent messages anyway.
        is MessageIndex -> listOf(buildJsonObject {
            put("type", "sms.index"); put("thread", id(value.threadId))
            put("ids", JsonArray(value.messageIds.map(::id).sortedDescending().take(1000).map(::JsonPrimitive)))
        })
        is CallInfo -> listOf(buildJsonObject {
            put("type", "call.state")
            put("state", when (value.callState) { CallState.Ringing -> "ringing"; CallState.InProgress -> "active"; CallState.MissedCall -> "missed"; CallState.Ended -> "ended" })
            put("number", address(value.phoneNumber)); put("name", clean(value.contactInfo?.displayName.orEmpty(), 240))
        })
        else -> null
    }

    /** Drop trailing rows until one event holds the answer. */
    private fun shrink(type: String, key: String, rows: List<JsonObject>, extra: JsonObjectBuilder.() -> Unit): JsonObject {
        var count = rows.size
        while (true) {
            val payload = buildJsonObject { put("type", type); extra(); put(key, JsonArray(rows.take(count))) }
            if (count == 0 || fits(payload)) return payload
            count--
        }
    }

    /** Up to 20 matching contacts for the root computer's search; never stored there. */
    fun contacts(query: String, all: List<ContactInfo>): JsonObject {
        val found = PhoneFeatureFrames.contacts(query, all).getValue("contacts").jsonArray.map { row ->
            val contact = row.jsonObject
            buildJsonObject {
                put("name", clean(contact.getValue("name").jsonPrimitive.content, 120))
                put("numbers", JsonArray(contact.getValue("numbers").jsonArray.map { address(it.jsonPrimitive.content, 40) }
                    .filter { it.isNotEmpty() }.distinct().take(5).map(::JsonPrimitive)))
            }
        }
        return shrink("contacts.results", "contacts", found) { put("query", clean(query.trim(), 64)) }
    }

    /** The last 50 calls, newest first, for the root computer's request. */
    fun callLog(calls: List<CallLogInfo>): JsonObject {
        val rows = PhoneFeatureFrames.callLog(calls).getValue("calls").jsonArray.map { row ->
            val call = row.jsonObject
            buildJsonObject {
                put("number", clean(call.getValue("number").jsonPrimitive.content, 120))
                put("name", clean(call.getValue("name").jsonPrimitive.content, 240))
                put("timestamp", time(call.getValue("timestamp").jsonPrimitive.long))
                put("duration", call.getValue("duration").jsonPrimitive.long.coerceIn(0, 1_000_000_000))
                put("type", call.getValue("type"))
            }
        }
        return shrink("calls.log", "calls", rows) {}
    }

    private fun text(payload: JsonObject, key: String): String {
        val value = payload.getValue(key)
        require(value is JsonPrimitive && value.isString)
        return value.content
    }
    private fun number(payload: JsonObject, key: String): Long {
        val value = payload.getValue(key)
        require(value is JsonPrimitive && !value.isString && Regex("0|[1-9][0-9]{0,15}").matches(value.content))
        return value.content.toLong().also { require(it <= MAX_SAFE) }
    }
    private fun wellFormed(value: String) = clean(value, value.length) == value
    private fun smsText(payload: JsonObject): String = text(payload, "text").also {
        require(it.isNotBlank() && it.codePointCount(0, it.length) <= 4096 && wellFormed(it))
    }

    /** Exact-shape validation of a decrypted phone action; null means ignore it. */
    fun command(payload: JsonObject): HostedPhoneCommand? = runCatching {
        val type = text(payload, "type")
        fun keys(vararg names: String) = require(payload.keys == setOf("type", *names))
        when (type) {
            "sms.sync" -> { keys(); HostedPhoneCommand.SmsSync }
            "calls.log.request" -> { keys(); HostedPhoneCommand.CallsLog }
            "sms.open" -> { keys("thread"); HostedPhoneCommand.SmsOpen(number(payload, "thread")) }
            "sms.send" -> { keys("thread", "text"); HostedPhoneCommand.SmsSend(number(payload, "thread"), smsText(payload)) }
            "sms.compose" -> {
                keys("addresses", "text")
                val addresses = payload.getValue("addresses").jsonArray
                require(addresses.size == 1)
                val value = addresses[0]
                require(value is JsonPrimitive && value.isString)
                val recipient = value.content
                require(recipient.isNotEmpty() && recipient.length <= 120 && recipient == address(recipient) && wellFormed(recipient))
                HostedPhoneCommand.SmsCompose(recipient, smsText(payload))
            }
            "call.command" -> { keys("operation")
                when (text(payload, "operation")) { "answer" -> HostedPhoneCommand.Call(true); "reject" -> HostedPhoneCommand.Call(false); else -> null } }
            "call.dial" -> { keys("number"); text(payload, "number").takeIf(PhoneFeatureFrames::dialable)?.let(HostedPhoneCommand::Dial) }
            "contacts.search" -> { keys("query")
                text(payload, "query").takeIf { it.isNotBlank() && it.length <= 64 && it.none { c -> c.code < 32 } && wellFormed(it) }
                    ?.let(HostedPhoneCommand::ContactsSearch) }
            else -> null
        }
    }.getOrNull()
}
