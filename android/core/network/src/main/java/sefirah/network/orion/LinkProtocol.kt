package sefirah.network.orion

import kotlinx.serialization.json.*
import java.util.UUID
import java.security.MessageDigest

/** Transport rules contain no Android state, keys or feature actions. */
class LinkProtocol(private val now: () -> Long = { System.currentTimeMillis() / 1000 }) {
    private data class ConversationKey(val thread: Long, val targets: List<String>?)
    private data class ConversationMemo(var latest: String?, var digest: String? = null, var checksum: Long? = null, var removed: Boolean = false)
    private data class Pending(val until: Long, val event: JsonObject, var sent: Boolean = false,
        val conversation: ConversationKey? = null, val digest: String? = null, var checksum: Long? = null)
    private val pending = linkedMapOf<String, Pending>()
    private val received = linkedMapOf<String, Long>()
    private val conversations = linkedMapOf<ConversationKey, ConversationMemo>()
    private var identity: String? = null
    /** Existing paired identity scopes pending actions and in-memory delivery knowledge. */
    @Synchronized fun identity(value: String?) {
        if (identity == value) return
        identity = value; pending.clear(); received.clear(); conversations.clear()
    }
    @Synchronized fun invalidateConversations() {
        conversations.values.forEach { it.digest = null; it.checksum = null }
    }
    /** Unknown/unaccepted checksums force the upstream producer to retry changes. */
    @Synchronized fun knownConversations(): List<Pair<Long, Long>> {
        prune()
        return conversations.filter { (key,memo) -> key.targets == null && (!memo.removed || memo.latest?.let(pending::get) != null) }
            .map { (key, memo) -> key.thread to (memo.checksum ?: Long.MIN_VALUE) }
    }
    @Synchronized fun publish(type: String, payload: JsonObject, targets: List<String>? = null, conversationChecksum: Long? = null): Boolean {
        prune()
        val conversation = if (type in setOf("sms.thread", "sms.remove"))
            payload["thread"]?.jsonPrimitive?.longOrNull?.let { ConversationKey(it, targets?.sorted()) } else null
        val digest = conversation?.let {
            MessageDigest.getInstance("SHA-256").digest((type+"\n"+payload.toString()).toByteArray(Charsets.UTF_8))
                .joinToString("") { byte -> "%02x".format(byte) }
        }
        val memo = conversation?.let(conversations::get)
        val latest = memo?.latest?.let(pending::get)
        if (latest != null && latest.digest == digest) {
            latest.checksum = conversationChecksum ?: latest.checksum
            return true // Reuse its pending ID until accepted or expired.
        }
        if (memo != null && latest == null && memo.digest == digest) {
            memo.checksum = conversationChecksum ?: memo.checksum
            return true // The hub already retained this exact state.
        }
        if (pending.size >= 512) return false
        val id = UUID.randomUUID().toString()
        val event = buildJsonObject {
            put("id", id); put("type", type); put("ttl_seconds", 60); put("payload", payload)
            targets?.let { put("targets", JsonArray(it.map(::JsonPrimitive))) }
        }
        pending[id] = Pending(now() + 60, event, conversation = conversation, digest = digest, checksum = conversationChecksum)
        if (conversation != null) {
            conversations[conversation] = ConversationMemo(id, memo?.digest, memo?.checksum, memo?.removed ?: false)
            while (conversations.size > 1024) conversations.remove(conversations.keys.first())
        }
        return true
    }
    @Synchronized fun discardDenied(allowed: (String) -> Boolean) {
        pending.entries.removeAll { (id, value) ->
            val discard = !allowed(value.event.getValue("type").jsonPrimitive.content)
            if (discard && value.conversation != null && conversations[value.conversation]?.latest == id)
                conversations.remove(value.conversation)
            discard
        }
    }
    @Synchronized fun outgoing(retry: Boolean = true, allowed: (String) -> Boolean = { true }): List<String> {
        prune()
        discardDenied(allowed)
        // A new publication sends only unsent events. Heartbeats and reconnect
        // explicitly retry pending IDs; adding N threads must not send N² frames.
        return pending.values.filter { retry || !it.sent }.map {
            it.sent = true
            buildJsonObject { put("op", "publish"); put("event", it.event) }.toString()
        }
    }
    @Synchronized fun accepted(id: String) {
        val accepted = pending.remove(id) ?: return
        accepted.conversation?.let { key -> conversations[key]?.let { memo ->
            // An older ACK must not overwrite knowledge of a newer queued update.
            if (memo.latest == id) {
                memo.latest = null; memo.digest = accepted.digest; memo.checksum = accepted.checksum
                memo.removed = accepted.event.getValue("type").jsonPrimitive.content == "sms.remove"
            }
        } }
    }
    @Synchronized fun receiveForIdentity(expected: String?, event: JsonObject, deliver: (JsonObject) -> Unit): String? =
        if(identity != expected) null else receive(event,deliver)
    @Synchronized fun receive(event: JsonObject, deliver: (JsonObject) -> Unit): String {
        prune()
        val id = event.getValue("id").jsonPrimitive.content
        require(UUID.fromString(id).toString() == id)
        val expires = event.getValue("expires_at").jsonPrimitive.double
        require(expires.isFinite())
        if (expires > now() && id !in received) {
            deliver(event) // Ack only after the handler succeeds.
            received[id] = now() + 86400
            while (received.size > 1000) received.remove(received.keys.first())
        }
        return buildJsonObject { put("op", "ack"); put("id", id) }.toString()
    }
    private fun prune() {
        pending.entries.removeAll { it.value.until <= now() }
        received.entries.removeAll { it.value <= now() }
    }
}
