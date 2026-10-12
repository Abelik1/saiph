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
        })
        is MessageList -> value.messages.take(10).chunked(2).map { chunk->"sms.messages" to buildJsonObject { put("thread",value.threadId);put("messages",JsonArray(chunk.map(::message))) } }
        is RemoveConversation -> listOf("sms.remove" to buildJsonObject { put("thread",value.threadId) })
        is MessageIndex -> listOf("sms.index" to buildJsonObject { put("thread",value.threadId);put("ids",JsonArray(value.messageIds.take(2000).map(::JsonPrimitive))) })
        is CallInfo -> listOf("call.state" to buildJsonObject {
            put("state",when(value.callState) { CallState.Ringing->"ringing";CallState.InProgress->"active";CallState.MissedCall->"missed";CallState.Ended->"ended" })
            put("number",value.phoneNumber.take(120));put("name",value.contactInfo?.displayName.orEmpty().take(240))
        })
        else -> null
    }
}
