package sefirah.network.orion

import kotlinx.serialization.json.*
import sefirah.domain.model.*

/** Pure boundary codec. Two message bodies per frame fit even with UTF-8 emoji. */
object PhoneFeatureFrames {
    private fun message(m: TextMessage)=buildJsonObject {
        put("id",m.uniqueId.coerceAtLeast(0));put("addresses",JsonArray(m.addresses.take(10).map { JsonPrimitive(it.take(120)) }))
        put("body",m.body.take(4096));put("timestamp",m.timestamp.coerceAtLeast(0))
        put("direction",if(m.messageType==1)"incoming" else "outgoing");put("subscription",m.subscriptionId)
    }
    fun encode(value: SocketMessage): List<Pair<String,JsonObject>>? = when(value) {
        is ConversationInfo -> listOf("sms.thread" to buildJsonObject {
            put("thread",value.threadId);put("recipients",JsonArray(value.recipients.take(10).map { JsonPrimitive(it.take(120)) }));put("message",message(value.message))
        }) + listOfNotNull(attachments(value.threadId,value.message))
        is MessageList -> value.messages.take(10).chunked(2).map { chunk->"sms.messages" to buildJsonObject { put("thread",value.threadId);put("messages",JsonArray(chunk.map(::message))) } } +
            value.messages.take(10).mapNotNull { attachments(value.threadId,it) }
        is RemoveConversation -> listOf("sms.remove" to buildJsonObject { put("thread",value.threadId) })
        is MessageIndex -> listOf("sms.index" to buildJsonObject { put("thread",value.threadId);put("ids",JsonArray(value.messageIds.take(2000).map(::JsonPrimitive))) })
        is CallInfo -> listOf("call.state" to buildJsonObject {
            put("state",when(value.callState) { CallState.Ringing->"ringing";CallState.InProgress->"active";CallState.MissedCall->"missed";CallState.Ended->"ended" })
            put("number",value.phoneNumber.take(120));put("name",value.contactInfo?.displayName.orEmpty().take(240))
        })
        is RingerModeState -> ringer(value.mode)?.let { listOf("ringer.state" to buildJsonObject { put("mode", it) }) }
        else -> null
    }
    /** MMS parts are announced by name only; their bytes travel directly when the computer asks. */
    fun attachments(thread: Long, m: TextMessage): Pair<String,JsonObject>? {
        val parts=m.attachments.orEmpty().filter { it.partId>=0 && !it.mimeType.startsWith("text/") && it.mimeType!="application/smil" }.take(10)
        if(parts.isEmpty())return null
        return "sms.attachments" to buildJsonObject {
            put("thread",thread);put("message",m.uniqueId.coerceAtLeast(0))
            put("parts",JsonArray(parts.map { buildJsonObject { put("part",it.partId);put("mime",it.mimeType.take(120));put("name",it.fileName.take(180)) } }))
        }
    }
    fun ringer(mode: Int) = when (mode) { 0 -> "silent"; 1 -> "vibrate"; 2 -> "ring"; else -> null }
    fun ringerMode(name: String) = when (name) { "silent" -> 0; "vibrate" -> 1; "ring" -> 2; else -> throw IllegalArgumentException() }
    /** At most 20 matching contacts with their numbers, for one computer's search. */
    fun contacts(query: String, all: List<ContactInfo>): JsonObject {
        val needle = query.trim().lowercase(); val digits = needle.filter(Char::isDigit)
        val matches = all.filter { it.displayName.lowercase().contains(needle) || (digits.length >= 3 && it.number.filter(Char::isDigit).contains(digits)) }
            .groupBy { it.displayName }.entries.take(20)
        return buildJsonObject {
            put("query", query.take(64))
            put("contacts", JsonArray(matches.map { (name, rows) -> buildJsonObject {
                put("name", name.take(120))
                put("numbers", JsonArray(rows.map { it.number.take(40) }.filter { it.isNotBlank() }.distinct().take(5).map(::JsonPrimitive)))
            } }))
        }
    }
    fun callLog(calls: List<CallLogInfo>) = buildJsonObject {
        put("calls", JsonArray(calls.sortedByDescending { it.timestampMillis }.take(50).map { call -> buildJsonObject {
            put("number", call.phoneNumber.take(120)); put("name", call.contactInfo?.displayName.orEmpty().take(240))
            put("timestamp", call.timestampMillis.coerceAtLeast(0)); put("duration", call.durationSeconds.coerceAtLeast(0))
            put("type", when (call.callType) { CallLogType.Incoming, CallLogType.AnsweredExternally -> "incoming"; CallLogType.Outgoing -> "outgoing"
                CallLogType.Missed -> "missed"; CallLogType.Rejected, CallLogType.Blocked -> "rejected"; else -> "other" })
        } }))
    }
    /** Ordinary numbers only: * and # make MMI codes that can change call forwarding. */
    fun dialable(number: String) = Regex("[0-9+() .-]{1,40}").matches(number) && number.any(Char::isDigit)
}
