// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import kotlinx.serialization.json.*

/**
 * A one-use local invitation sent by an approved computer inside a sealed Cloud
 * envelope instead of a QR code. The phone half of the format in the desktop's
 * `session_offer.py`; both test suites read `session-offer-vectors.json`.
 *
 * Decryption proves which approved device sent it. The runtime additionally
 * requires a current, subscribed computer, shows each offer at most once and
 * never starts anything by itself: the owner taps the prompt, verifies with the
 * screen lock and grants camera access in the foreground. The desktop claims the
 * invitation's bearer secret on first use, so a replay or a second phone gets
 * nothing. Never put the invitation in logs, URLs, saved state or intent data.
 */
internal class SessionOffer(val id: String, val service: String, val expiresAt: Long, val invite: String,
    private val cameraOffer: CameraOffer?, private val screenOffer: ScreenOffer? = null, private val fileOffer: FileOffer? = null) {
    /** The parsed invitation of a "camera" offer. */
    val camera: CameraOffer get() = checkNotNull(cameraOffer) { "Not a camera offer." }
    /** The parsed invitation of a "screen" offer (docs/PHONE_SCREEN.md). */
    val screen: ScreenOffer get() = checkNotNull(screenOffer) { "Not a phone screen offer." }
    /** The parsed invitation of a "file" offer (docs/LAN_FILES.md): fetched or uploaded without a prompt. */
    val file: FileOffer get() = checkNotNull(fileOffer) { "Not a file offer." }
    companion object {
        const val TYPE = "session.offer"
        /** The sending computer's "this offer is answered, cancelled or expired": drop its prompt (session_offer.py). */
        const val CLOSE_TYPE = "session.close"
        const val VERSION = 1
        const val MAX_LIFETIME = 120L
        /** Known services; each validates its own invitation format. */
        val SERVICES = setOf("camera", "screen", "file")

        private fun integer(value: JsonElement?): Long {
            val primitive = value as? JsonPrimitive ?: throw IllegalArgumentException()
            require(!primitive.isString && primitive.booleanOrNull == null)
            return primitive.content.toLong()
        }
        private fun text(value: JsonElement?): String {
            val primitive = value as? JsonPrimitive ?: throw IllegalArgumentException()
            require(primitive.isString)
            return primitive.content
        }

        /** This phone withdraws from an offer it received (a "put" invitation it could not use). */
        fun closePayload(id: String) = buildJsonObject { put("type", CLOSE_TYPE); put("version", VERSION); put("id", id) }
            .also { checkNotNull(parseClose(it)) }

        /** The offer ID of an exact `session.close`, or null for anything else. */
        fun parseClose(payload: JsonObject): String? = runCatching {
            require(payload.keys == setOf("type", "version", "id"))
            require(text(payload["type"]) == CLOSE_TYPE && integer(payload["version"]) == VERSION.toLong())
            text(payload["id"]).also { require(Regex("[a-f0-9]{32}").matches(it)) }
        }.getOrNull()

        /** The validated offer, or an exception for anything else. */
        fun parse(payload: JsonObject, now: Long = System.currentTimeMillis() / 1000): SessionOffer {
            require(payload.keys == setOf("type", "version", "id", "service", "expires_at", "invite"))
            require(text(payload["type"]) == TYPE && integer(payload["version"]) == VERSION.toLong())
            val id = text(payload["id"]); val service = text(payload["service"])
            require(Regex("[a-f0-9]{32}").matches(id) && service in SERVICES)
            val expiresAt = integer(payload["expires_at"])
            require(expiresAt > now && expiresAt <= now + MAX_LIFETIME)
            val invite = text(payload["invite"])
            // The scanner's own checks: private literal IPv4, pinned certificate, bounded profile.
            if (service == "file") {
                val file = FileOffer.parse(invite, now)
                require(file.expires == expiresAt)
                return SessionOffer(id, service, expiresAt, invite, null, null, file)
            }
            if (service == "screen") {
                val screen = ScreenOffer.parse(invite, now)
                require(screen.expires == expiresAt)
                return SessionOffer(id, service, expiresAt, invite, null, screen)
            }
            val camera = CameraOffer.parse(invite, now)
            require(camera.expires == expiresAt)
            return SessionOffer(id, service, expiresAt, invite, camera)
        }
    }
}

/**
 * Offers waiting for the owner's tap, in memory only: a restarted process
 * forgets them, which is safe because each expires within two minutes.
 * [take] hands an offer out once.
 */
internal object SessionOffers {
    class Pending(val offer: SessionOffer, val computer: String, val source: String)
    private val pending = LinkedHashMap<String, Pending>()
    private val shown = LinkedHashMap<String, Long>()

    /** False for a repeated or excess offer; true when it should be shown. */
    @Synchronized fun put(offer: SessionOffer, computer: String, source: String, now: Long = System.currentTimeMillis() / 1000): Boolean {
        prune(now)
        if (offer.id in shown || shown.size >= 64) return false
        shown[offer.id] = offer.expiresAt
        // One camera prompt at a time: a newer offer replaces an older one.
        pending.values.removeAll { it.offer.service == offer.service }
        pending[offer.id] = Pending(offer, computer, source)
        return true
    }
    @Synchronized fun take(id: String, now: Long = System.currentTimeMillis() / 1000): Pending? {
        prune(now)
        return pending.remove(id)
    }
    @Synchronized fun peek(id: String, now: Long = System.currentTimeMillis() / 1000): Pending? {
        prune(now)
        return pending[id]
    }
    /** The computer that sent offer [id] closed it; null when it is not pending or came from someone else. */
    @Synchronized fun close(id: String, source: String, now: Long = System.currentTimeMillis() / 1000): Pending? {
        prune(now)
        pending[id]?.takeIf { it.source == source } ?: return null
        return pending.remove(id)
    }
    /** The owner chose Not now: the offer is dropped (its ID stays shown, so a replay is not prompted again). */
    @Synchronized fun decline(id: String) { pending.remove(id) }
    /** Offers still waiting, newest last. */
    @Synchronized fun active(now: Long = System.currentTimeMillis() / 1000): List<Pending> { prune(now); return pending.values.toList() }
    /** A revoked or unsubscribed computer's offers disappear at once. */
    @Synchronized fun retain(sources: Set<String>) { pending.values.removeAll { it.source !in sources } }
    /** Sign-out or reset. Replays stay refused by the runtime's durable receipts. */
    @Synchronized fun clear() { pending.clear(); shown.clear() }
    private fun prune(now: Long) {
        pending.values.removeAll { it.offer.expiresAt <= now }
        shown.values.removeAll { it <= now }
    }
}
