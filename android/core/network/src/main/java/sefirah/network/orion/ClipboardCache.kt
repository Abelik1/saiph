package sefirah.network.orion

import java.security.MessageDigest

/**
 * The value most recently synced, suppressed only as an echo. Hashes only, shared
 * across worker/app callbacks; no clipboard content in logs.
 *
 * A remote write or local publish records its (mime, digest); change callbacks for
 * that value within [ECHO_MILLIS] are not rebroadcast. Content seen earlier is not
 * blocked: copying A, B, then A again must deliver A again.
 */
class ClipboardCache(private val now: () -> Long = { System.currentTimeMillis() }) {
    private var current: String? = null
    private var at = 0L
    @Synchronized fun claim(mime: String, digest: String): Boolean {
        val key = "$mime:$digest"
        if (key == current && now() - at < ECHO_MILLIS) return false
        current = key
        at = now()
        return true
    }
    companion object {
        const val ECHO_MILLIS = 10_000L
        fun hash(data: ByteArray) = MessageDigest.getInstance("SHA-256").digest(data).joinToString("") { "%02x".format(it) }
    }
}
