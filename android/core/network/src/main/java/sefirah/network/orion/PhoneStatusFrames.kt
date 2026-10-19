// SPDX-License-Identifier: GPL-3.0-only
package sefirah.network.orion

import kotlinx.serialization.json.*

/** What the phone shows in a computer's device header; null means unknown or not readable. */
data class PhoneStatus(
    val battery: Int?, val charging: Boolean,
    val wifi: Boolean?, val cellular: Boolean?, val metered: Boolean,
    val bluetooth: Boolean?, val signal: Int?,
    val ringer: String?, val dnd: Boolean?,
    val controls: List<String>, val mobileData: Boolean, val paused: Boolean,
    /** Wi-Fi bars 0-4; null when Wi-Fi is not connected. Sent in `phone.signal`, not `phone.status`. */
    val wifiLevel: Int? = null,
    /** Mobile bars 0-4 from the SIM, whatever network is active; null without mobile service. */
    val cellularLevel: Int? = null,
)

/** A quick action from a computer, after exact-shape validation. */
sealed interface PhoneControlCommand {
    /** "Refresh" on the computer: send that computer the current status again. */
    data object Status : PhoneControlCommand
    data object Ring : PhoneControlCommand
    /** Stop a Find phone ring from the computer, as Stop on the phone does. */
    data object RingStop : PhoneControlCommand
    data class Ringer(val mode: String) : PhoneControlCommand
    data class Dnd(val active: Boolean) : PhoneControlCommand
    data class Media(val source: String, val action: String) : PhoneControlCommand
    data object Wallpaper : PhoneControlCommand
    data object Hotspot : PhoneControlCommand
    data class MobileData(val allowed: Boolean) : PhoneControlCommand
}

/** The two transports under the shared phone feature layer. */
enum class PhoneTransport {
    /** Self-hosted Hub events: `{type, payload}`, relayed by the Hub, which validates the types it knows. */
    LINK,
    /** Saiph Cloud: one sealed payload `{"type": ..., ...}` per subscribed computer. */
    HOSTED,
}

/**
 * Phone status and quick actions, shared by the self-hosted Hub and Saiph Cloud:
 * `phone.status`, the `phone.wallpaper` answer (and Cloud's `media.state`) from the
 * phone, quick actions back. Pure codec and policy; the desktop's
 * `phone_status.py` and the Hub's `features.py` apply the same shapes and limits.
 *
 * The controls a phone accepts are listed inside `phone.status`, never in a
 * capabilities list: an older Cloud desktop rejects a capabilities event with
 * names it does not know, and would lose texts and calls with it. A Hub phone
 * still advertises its older capabilities (ring, ringer, media) for older desktops.
 */
object PhoneStatusFrames {
    const val STATUS = "phone.status"
    const val MEDIA = "media.state"
    const val WALLPAPER = "phone.wallpaper"
    /**
     * Wi-Fi and mobile bars, sent with every `phone.status`. A separate type, not
     * new `phone.status` fields: older desktops and Hubs refuse unknown fields in
     * a type they know, but ignore or relay a type they do not.
     */
    const val SIGNAL = "phone.signal"
    /**
     * Find phone started (seconds left) or stopped, sent to every computer on each change.
     * Released desktops ignore it; it also tells newer ones this phone takes `phone.ring.stop`.
     */
    const val RING_STATE = "phone.ring.state"
    /** A ring lasts 30 seconds; the desktop believes no more than this. */
    const val RING_SECONDS_MAX = 120L
    val COMMAND_CONTROL = mapOf("phone.status.request" to "status", "phone.ring" to "ring", "phone.ringer" to "ringer", "phone.dnd" to "dnd", "media.command" to "media",
        "phone.wallpaper.request" to "wallpaper", "phone.hotspot" to "hotspot", "phone.mobile_data" to "mobile_data",
        "phone.ring.stop" to "ring")
    /** Controls each transport carries. Sync over mobile data is a Cloud sync setting. */
    val TRANSPORT_CONTROLS = mapOf(PhoneTransport.LINK to setOf("status", "ring", "ringer", "dnd", "media", "hotspot", "wallpaper"),
        PhoneTransport.HOSTED to COMMAND_CONTROL.values.toSet())
    /**
     * Quick actions a Hub phone takes through this layer. Ring, ringer and media
     * commands keep their older Hub path, which older desktops already use.
     */
    val LINK_COMMANDS = setOf("phone.status.request", "phone.dnd", "phone.hotspot", "phone.wallpaper.request", "phone.ring.stop")
    /** Battery and network changes wait this long after the last status. */
    const val MIN_INTERVAL = 15_000L
    /** A change in signal bars alone waits this long, so flapping bars cannot cause a storm. */
    const val SIGNAL_INTERVAL = 15_000L
    /** An unchanged status is resent this often, so a reconnected computer catches up. */
    const val REFRESH = 600_000L
    /** One computer's Refresh is honoured at most this often. */
    const val REFRESH_REQUEST = 10_000L
    private val RINGER = setOf("ring", "vibrate", "silent")
    private val MEDIA_ACTIONS = setOf("play", "pause", "next", "previous")

    /**
     * Quick actions this phone accepts now over [transport]. [shared] is the
     * owner's "Status and quick controls" switch; ringer and Do Not Disturb need
     * Do Not Disturb access, media needs notification access, the wallpaper needs
     * storage access.
     */
    fun controls(shared: Boolean, policy: Boolean, notifications: Boolean, wallpaper: Boolean,
                 transport: PhoneTransport = PhoneTransport.HOSTED): List<String> = if (!shared) emptyList() else buildList {
        add("status"); add("ring")
        if (policy) { add("ringer"); add("dnd") }
        if (notifications) add("media")
        if (wallpaper) add("wallpaper")
        add("hotspot"); add("mobile_data")
    }.filter { it in TRANSPORT_CONTROLS.getValue(transport) }

    /** Whether a subscribed Cloud computer may run this quick action now. */
    fun allowed(type: String, source: String, subscribers: Set<String>, controls: List<String>): Boolean =
        source in subscribers && allowed(type, controls)

    /** Whether this phone lists the quick action now (the Hub has authenticated the sender). */
    fun allowed(type: String, controls: List<String>): Boolean = COMMAND_CONTROL[type]?.let { it in controls } == true

    /** A quick action relayed by the Hub that this layer runs, or null to leave it to the older Hub path or ignore it. */
    fun linkCommand(type: String, body: JsonObject, controls: List<String>): PhoneControlCommand? =
        if (type in LINK_COMMANDS && allowed(type, controls)) command(type, body) else null

    /** What a phone sends after its owner turns status sharing off: everything unknown, no controls. */
    fun hidden(mobileData: Boolean, paused: Boolean) = PhoneStatus(null, false, null, null, false, null, null, null, null, emptyList(), mobileData, paused)

    /** The status body both transports carry; the Hub event payload. */
    fun body(status: PhoneStatus) = buildJsonObject {
        put("battery", status.battery?.coerceIn(0, 100)); put("charging", status.charging)
        put("wifi", status.wifi); put("cellular", status.cellular); put("metered", status.metered)
        put("bluetooth", status.bluetooth); put("signal", status.signal?.coerceIn(0, 4))
        put("ringer", status.ringer?.takeIf { it in RINGER }); put("dnd", status.dnd)
        put("controls", JsonArray(status.controls.filter { it in COMMAND_CONTROL.values }.distinct().map(::JsonPrimitive)))
        put("mobile_data", status.mobileData); put("paused", status.paused)
    }

    /** The sealed Cloud payload: the same body with its type inside. */
    fun payload(status: PhoneStatus) = JsonObject(mapOf("type" to JsonPrimitive(STATUS)) + body(status))

    /** The `phone.signal` body both transports carry; the Hub event payload. */
    fun signalBody(status: PhoneStatus) = buildJsonObject {
        put("wifi_level", status.wifiLevel?.coerceIn(0, 4)); put("cellular_level", status.cellularLevel?.coerceIn(0, 4))
    }

    /** The sealed Cloud `phone.signal` payload. */
    fun signalPayload(status: PhoneStatus) = JsonObject(mapOf("type" to JsonPrimitive(SIGNAL)) + signalBody(status))

    /** Bars 0-4 from a reading on a 0..[max] scale, as Android's own status bar draws them. */
    fun bars(level: Int, max: Int): Int? = if (max <= 0 || level < 0) null else (level.coerceAtMost(max) * 4 + max / 2) / max

    private fun urgent(before: PhoneStatus, after: PhoneStatus) = before.ringer != after.ringer || before.dnd != after.dnd ||
        before.charging != after.charging || before.paused != after.paused || before.controls != after.controls ||
        before.mobileData != after.mobileData || before.wifi != after.wifi || before.bluetooth != after.bluetooth

    /**
     * Send a new status now? Visible switches (ringer, Do Not Disturb, charging,
     * Wi-Fi, Bluetooth, controls) go at once; battery level after [MIN_INTERVAL];
     * Wi-Fi or mobile bars alone after [SIGNAL_INTERVAL]; an unchanged status every [REFRESH].
     */
    fun due(before: PhoneStatus?, sentAt: Long, after: PhoneStatus, now: Long): Boolean {
        if (before == null) return true
        val elapsed = now - sentAt
        if (elapsed < 0) return true // The clock moved back; resend rather than stall.
        if (after == before) return elapsed >= REFRESH
        if (urgent(before, after)) return true
        if (after.copy(signal = before.signal, wifiLevel = before.wifiLevel, cellularLevel = before.cellularLevel) == before)
            return elapsed >= SIGNAL_INTERVAL
        return elapsed >= MIN_INTERVAL
    }

    /**
     * The merged media sessions for Cloud: no position or volume, so a playing
     * track does not publish every tick. Hub phones keep their older, fuller
     * `media.state` shape, which older Hubs require.
     */
    fun media(state: JsonObject): JsonObject {
        val sessions = state["sessions"]?.jsonArray.orEmpty().takeLast(5).map { row ->
            val session = row.jsonObject
            fun text(key: String, max: Int) = HostedPhoneFrames.clean(session[key]?.jsonPrimitive?.contentOrNull.orEmpty(), max)
            fun flag(key: String) = session[key]?.jsonPrimitive?.booleanOrNull ?: false
            buildJsonObject {
                put("source", text("source", 240)); put("app", text("app", 120))
                put("title", text("title", 240)); put("artist", text("artist", 240))
                put("playing", flag("playing")); put("can_play", flag("can_play")); put("can_pause", flag("can_pause"))
                put("can_next", flag("can_next")); put("can_previous", flag("can_previous"))
            }
        }.filter { it.getValue("source").jsonPrimitive.content.isNotEmpty() }
        var count = sessions.size
        while (true) {
            val payload = buildJsonObject { put("type", MEDIA); put("sessions", JsonArray(sessions.takeLast(count))) }
            if (count == 0 || HostedPhoneFrames.fits(payload)) return payload
            count--
        }
    }

    /** The ring-state body both transports carry (the Hub event payload): seconds left, 0 once stopped. */
    fun ringStateBody(state: FindPhoneRing.State, now: Long): JsonObject = buildJsonObject {
        val ringing = state as? FindPhoneRing.State.Ringing
        val seconds = ringing?.let { ((it.until - now + 999) / 1000).coerceIn(1, RING_SECONDS_MAX) } ?: 0L
        put("ringing", ringing != null); put("seconds", seconds)
    }

    /** The sealed Cloud payload: the same body with its type inside. */
    fun ringState(state: FindPhoneRing.State, now: Long): JsonObject =
        JsonObject(mapOf("type" to JsonPrimitive(RING_STATE)) + ringStateBody(state, now))

    /** A JPEG data URL of at most 12,000 bytes and 384 pixels a side, or "" when Android does not allow reading it. */
    fun wallpaper(jpeg: ByteArray?): JsonObject = JsonObject(mapOf("type" to JsonPrimitive(WALLPAPER)) + wallpaperBody(jpeg))

    /** The wallpaper answer body both transports carry; the Hub event payload. */
    fun wallpaperBody(jpeg: ByteArray?): JsonObject = buildJsonObject {
        put("preview", if (jpeg != null && jpeg.size in 4..12_000) "data:image/jpeg;base64," + java.util.Base64.getEncoder().encodeToString(jpeg) else "")
    }

    /** Exact-shape validation of a quick action body (without "type"); null means ignore it. */
    fun command(type: String, body: JsonObject): PhoneControlCommand? = runCatching {
        fun keys(vararg names: String) = require(body.keys == setOf(*names))
        fun string(key: String): String { val value = body.getValue(key); require(value is JsonPrimitive && value.isString); return value.content }
        fun flag(key: String): Boolean { val value = body.getValue(key); require(value is JsonPrimitive && !value.isString); return value.boolean }
        when (type) {
            "phone.status.request" -> { keys(); PhoneControlCommand.Status }
            "phone.ring" -> { keys(); PhoneControlCommand.Ring }
            "phone.ring.stop" -> { keys(); PhoneControlCommand.RingStop }
            "phone.ringer" -> { keys("mode"); string("mode").takeIf { it in RINGER }?.let(PhoneControlCommand::Ringer) }
            "phone.dnd" -> { keys("active"); PhoneControlCommand.Dnd(flag("active")) }
            "media.command" -> {
                keys("source", "action")
                val source = string("source"); val action = string("action")
                require(source.isNotEmpty() && source.length <= 240 && action in MEDIA_ACTIONS)
                PhoneControlCommand.Media(source, action)
            }
            "phone.wallpaper.request" -> { keys(); PhoneControlCommand.Wallpaper }
            "phone.hotspot" -> { keys(); PhoneControlCommand.Hotspot }
            "phone.mobile_data" -> { keys("allowed"); PhoneControlCommand.MobileData(flag("allowed")) }
            else -> null
        }
    }.getOrNull()

    /** A decrypted Cloud quick action: the same body with its type inside. */
    fun command(payload: JsonObject): PhoneControlCommand? {
        val type = (payload["type"] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: return null
        return command(type, JsonObject(payload - "type"))
    }
}

/**
 * When to send the shared status, and to whom. One per transport: the Hub fans a
 * single event out to every paired computer ([BROADCAST]); Saiph Cloud seals one
 * copy per subscribed computer. Pure state, so both transports keep the same
 * rate limits ([PhoneStatusFrames.due]) and the same Refresh rule.
 */
class PhoneStatusPublisher {
    companion object { const val BROADCAST = "" }
    private var last: PhoneStatus? = null
    private var sentAt = 0L
    private val recipients = mutableSetOf<String>()
    private val asked = mutableMapOf<String, Long>()

    /**
     * Send [current] to the [targets] that need it. [force] sends to all (a pause
     * notice must reach everyone). [send] returns false when nothing was queued,
     * so that target is tried again on the next pass. Returns the targets sent to.
     */
    @Synchronized fun sync(targets: Set<String>, current: PhoneStatus, force: Boolean, now: Long, send: (String) -> Boolean): Set<String> {
        recipients.retainAll(targets)
        if (targets.isEmpty()) return emptySet()
        val due = force || PhoneStatusFrames.due(last, sentAt, current, now)
        val chosen = if (due) targets else targets - recipients
        val sent = chosen.filterTo(mutableSetOf()) { send(it) }
        if (sent == targets) { last = current; sentAt = now }
        recipients.addAll(sent)
        return sent
    }

    /** A computer's Refresh: resend to [recipient] on the next pass, at most every [PhoneStatusFrames.REFRESH_REQUEST] per [source]. */
    @Synchronized fun refresh(source: String, recipient: String, now: Long): Boolean {
        if (now - (asked[source] ?: Long.MIN_VALUE / 2) in 0 until PhoneStatusFrames.REFRESH_REQUEST) return false
        asked[source] = now; recipients.remove(recipient)
        return true
    }

    /** Settings changed: the next pass sends to every target. */
    @Synchronized fun invalidate() { last = null }

    /** Signed out or reconnected: forget what every computer has. */
    @Synchronized fun reset() { last = null; sentAt = 0; recipients.clear(); asked.clear() }
}
