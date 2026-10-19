// SPDX-License-Identifier: GPL-3.0-only
package sefirah.network.orion

import kotlinx.serialization.json.*

/** A notification action from an approved computer, after exact-shape validation. */
sealed interface HostedNotificationCommand {
    val key: String
    data class Action(override val key: String, val index: Int) : HostedNotificationCommand
    data class Reply(override val key: String, val replyKey: String, val text: String) : HostedNotificationCommand
    data class Open(override val key: String) : HostedNotificationCommand
}

/**
 * Notification buttons and inline replies over Saiph Cloud, as a Hub phone offers
 * them (feature "notification-actions", listed in `phone.features`). The desktop's
 * `hosted_features.py` applies the same shapes and limits.
 *
 * `notification.actions` goes to every approved computer just before the matching
 * `notification.upsert`; desktops released before it ignore the type. The phone
 * acts on `notification.action`, `notification.reply` and `notification.open`
 * only from a current roster member (every approved computer receives the
 * notifications), only with notification access and at most once per event.
 */
object HostedNotificationFrames {
    const val ACTIONS = "notification.actions"
    const val ACTION = "notification.action"
    const val REPLY = "notification.reply"
    const val OPEN = "notification.open"
    val COMMANDS = setOf(ACTION, REPLY, OPEN)
    private const val MAX_TIMESTAMP = 253_402_300_799_999L
    private val KEY = Regex("[A-Za-z0-9._:|/+=@-]{1,256}")

    /** Buttons and the reply key of one notification; null when it has neither, or its key cannot travel. */
    fun actions(key: String, timestamp: Long, actions: List<Pair<Int, String?>>, replyKey: String?): JsonObject? {
        if (!KEY.matches(key)) return null
        val buttons = actions.filter { it.first in 0..99 }.distinctBy { it.first }.take(10)
        val reply = replyKey?.takeIf { it.length in 1..240 && it.none { c -> c.code < 32 || c.code == 127 } && wellFormed(it) }.orEmpty()
        if (buttons.isEmpty() && reply.isEmpty()) return null
        return buildJsonObject {
            put("type", ACTIONS); put("key", key); put("timestamp", timestamp.coerceIn(0, MAX_TIMESTAMP))
            put("actions", JsonArray(buttons.map { (index, label) -> buildJsonObject {
                put("index", index); put("label", HostedPhoneFrames.clean(label.orEmpty(), 120))
            } }))
            put("reply_key", reply)
        }
    }

    private fun wellFormed(value: String) = HostedPhoneFrames.clean(value, value.length) == value
    private fun text(payload: JsonObject, name: String): String {
        val value = payload.getValue(name)
        require(value is JsonPrimitive && value.isString)
        return value.content
    }

    /** Exact-shape validation of a decrypted notification action; null means ignore it. */
    fun command(payload: JsonObject): HostedNotificationCommand? = runCatching {
        fun keys(vararg names: String) = require(payload.keys == setOf("type", "key", *names))
        val key = text(payload, "key").also { require(KEY.matches(it)) }
        when (text(payload, "type")) {
            ACTION -> {
                keys("index")
                val index = payload.getValue("index")
                require(index is JsonPrimitive && !index.isString && Regex("0|[1-9][0-9]?").matches(index.content))
                HostedNotificationCommand.Action(key, index.content.toInt())
            }
            REPLY -> {
                keys("reply_key", "text")
                val replyKey = text(payload, "reply_key")
                require(replyKey.length in 1..240 && replyKey.none { it.code < 32 || it.code == 127 } && wellFormed(replyKey))
                val reply = text(payload, "text")
                require(reply.isNotBlank() && reply.codePointCount(0, reply.length) <= 4096 && wellFormed(reply))
                HostedNotificationCommand.Reply(key, replyKey, reply)
            }
            OPEN -> { keys(); HostedNotificationCommand.Open(key) }
            else -> null
        }
    }.getOrNull()
}
