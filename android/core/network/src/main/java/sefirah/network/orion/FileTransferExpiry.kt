package sefirah.network.orion

import kotlinx.serialization.json.*

/** Direct offers last 15 minutes. A short bus TTL is not the download deadline. */
internal object FileTransferExpiry {
    const val SECONDS = 900
    fun expired(event: JsonObject, now: Double): Boolean {
        val created = runCatching { event["created_at"]?.jsonPrimitive?.doubleOrNull }.getOrNull() ?: return true
        return !created.isFinite() || created < 0 || created > now + 60 || now >= created + SECONDS
    }
    fun pending(entries: Map<String, *>, now: Double): List<String> = entries.mapNotNull { (key, value) ->
        if (!key.startsWith("pending:")) return@mapNotNull null
        val event = runCatching { Json.parseToJsonElement(value as String).jsonObject }.getOrNull()
        if (event == null || expired(event, now)) key.removePrefix("pending:") else null
    }
}
