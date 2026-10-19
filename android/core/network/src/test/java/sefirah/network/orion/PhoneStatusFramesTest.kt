// SPDX-License-Identifier: GPL-3.0-only
package sefirah.network.orion

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

/** Synthetic values only. Mirrors the desktop's tests/test_hosted_phone.py and tests/test_phone_status_shared.py shapes. */
class PhoneStatusFramesTest {
    companion object {
        const val STATUS_WIRE = """{"battery":76,"bluetooth":true,"cellular":false,"charging":true,"controls":["status","ring","ringer","dnd","media","hotspot","mobile_data"],"dnd":false,"metered":false,"mobile_data":true,"paused":false,"ringer":"vibrate","signal":3,"type":"phone.status","wifi":true}"""
        const val HIDDEN_WIRE = """{"battery":null,"bluetooth":null,"cellular":null,"charging":false,"controls":[],"dnd":null,"metered":false,"mobile_data":false,"paused":true,"ringer":null,"signal":null,"type":"phone.status","wifi":null}"""
        /** The Hub event body; tests/test_phone_status_shared.py checks the same literal. */
        const val LINK_STATUS_WIRE = """{"battery":76,"bluetooth":true,"cellular":false,"charging":true,"controls":["status","ring","ringer","dnd","media","hotspot"],"dnd":false,"metered":false,"mobile_data":true,"paused":false,"ringer":"vibrate","signal":3,"wifi":true}"""
        /** phone.signal as Cloud seals it; tests/test_phone_status_shared.py checks the same literals. */
        const val SIGNAL_WIRE = """{"cellular_level":3,"type":"phone.signal","wifi_level":2}"""
        const val LINK_SIGNAL_WIRE = """{"cellular_level":null,"wifi_level":null}"""
        const val MEDIA_WIRE = """{"sessions":[{"app":"Synthetic Player","artist":"Test Artist","can_next":true,"can_pause":true,"can_play":false,"can_previous":false,"playing":true,"source":"org.example.player","title":"Test Track"}],"type":"media.state"}"""
    }
    private val controls = PhoneStatusFrames.controls(shared = true, policy = true, notifications = true, wallpaper = false)
    private fun status(battery: Int? = 76, charging: Boolean = true, ringer: String? = "vibrate", signal: Int? = 3, wifi: Boolean? = true,
                       wifiLevel: Int? = 2, cellularLevel: Int? = 3) =
        PhoneStatus(battery, charging, wifi, false, false, true, signal, ringer, false, controls, mobileData = true, paused = false,
            wifiLevel = wifiLevel, cellularLevel = cellularLevel)
    private fun canonical(value: JsonObject) = HostedEnvelope.canonical(value).toString(Charsets.UTF_8)

    @Test fun statusMatchesTheDesktopWireShape() {
        assertEquals(STATUS_WIRE, canonical(PhoneStatusFrames.payload(status())))
        assertEquals(HIDDEN_WIRE, canonical(PhoneStatusFrames.payload(PhoneStatusFrames.hidden(mobileData = false, paused = true))))
        // Out-of-range readings are clamped, unknown ringer names dropped.
        val odd = PhoneStatusFrames.payload(status(battery = 140, signal = 9, ringer = "loud"))
        assertEquals(100, odd.getValue("battery").jsonPrimitive.int)
        assertEquals(4, odd.getValue("signal").jsonPrimitive.int)
        assertEquals(JsonNull, odd.getValue("ringer"))
    }

    @Test fun controlsFollowTheSwitchAndAndroidAccess() {
        assertEquals(emptyList<String>(), PhoneStatusFrames.controls(false, true, true, true))
        assertEquals(listOf("status", "ring", "hotspot", "mobile_data"), PhoneStatusFrames.controls(true, false, false, false))
        assertEquals(listOf("status", "ring", "ringer", "dnd", "media", "wallpaper", "hotspot", "mobile_data"), PhoneStatusFrames.controls(true, true, true, true))
        // Never in phone.capabilities: older desktops reject capability names they do not know.
        assertTrue(PhoneStatusFrames.COMMAND_CONTROL.values.none { it in HostedPhoneFrames.capabilities(FeatureAccess(), true, true) })
        assertTrue(PhoneStatusFrames.allowed("phone.ringer", "desk", setOf("desk"), controls))
        assertFalse(PhoneStatusFrames.allowed("phone.ringer", "stranger", setOf("desk"), controls))
        assertFalse(PhoneStatusFrames.allowed("phone.ringer", "desk", setOf("desk"), PhoneStatusFrames.controls(true, false, true, false)))
        assertFalse(PhoneStatusFrames.allowed("phone.wallpaper.request", "desk", setOf("desk"), controls))
        assertFalse(PhoneStatusFrames.allowed("sms.send", "desk", setOf("desk"), controls))
    }

    @Test fun statusIsSentOnChangeWithoutStorms() {
        val first = status()
        assertTrue(PhoneStatusFrames.due(null, 0, first, 1_000))
        // Unchanged: only the ten-minute refresh.
        assertFalse(PhoneStatusFrames.due(first, 0, first, PhoneStatusFrames.REFRESH - 1))
        assertTrue(PhoneStatusFrames.due(first, 0, first, PhoneStatusFrames.REFRESH))
        // Battery level waits 15 seconds; charging, ringer and Wi-Fi go at once.
        assertFalse(PhoneStatusFrames.due(first, 0, status(battery = 75), 5_000))
        assertTrue(PhoneStatusFrames.due(first, 0, status(battery = 75), PhoneStatusFrames.MIN_INTERVAL))
        assertTrue(PhoneStatusFrames.due(first, 0, status(charging = false), 1))
        assertTrue(PhoneStatusFrames.due(first, 0, status(ringer = "silent"), 1))
        assertTrue(PhoneStatusFrames.due(first, 0, status(wifi = false), 1))
        // Signal bars alone (mobile or Wi-Fi) wait 15 seconds.
        assertEquals(15_000L, PhoneStatusFrames.SIGNAL_INTERVAL)
        for (changed in listOf(status(signal = 2, cellularLevel = 2), status(wifiLevel = 1), status(cellularLevel = null))) {
            assertFalse(PhoneStatusFrames.due(first, 0, changed, 10_000))
            assertTrue(PhoneStatusFrames.due(first, 0, changed, PhoneStatusFrames.SIGNAL_INTERVAL))
        }
        // A clock moved backwards never stalls updates.
        assertTrue(PhoneStatusFrames.due(first, 10_000, status(battery = 75), 5_000))
    }

    @Test fun mediaDropsPositionAndKeepsOneEventSmall() {
        val merged = buildJsonObject { put("sessions", buildJsonArray {
            add(buildJsonObject {
                put("source", "org.example.player"); put("app", "Synthetic Player"); put("title", "Test Track"); put("artist", "Test Artist")
                put("playing", true); put("can_play", false); put("can_pause", true); put("can_next", true); put("can_previous", false)
                put("can_seek", true); put("position_ms", 4200); put("length_ms", 180_000); put("volume", 40)
            })
        }) }
        assertEquals(MEDIA_WIRE, canonical(PhoneStatusFrames.media(merged)))
        val crowded = buildJsonObject { put("sessions", JsonArray((1..9).map { index -> buildJsonObject {
            put("source", "org.example.p$index"); put("app", "\u0001".repeat(120)); put("title", "\u0002".repeat(240)); put("artist", "\u0003".repeat(240))
        } })) }
        val trimmed = PhoneStatusFrames.media(crowded)
        assertTrue(HostedPhoneFrames.fits(trimmed))
        assertTrue(trimmed.getValue("sessions").jsonArray.size in 1..5)
    }

    @Test fun quickActionsHaveExactShapes() {
        fun parse(json: String) = PhoneStatusFrames.command(Json.parseToJsonElement(json).jsonObject)
        assertEquals(PhoneControlCommand.Ring, parse("""{"type":"phone.ring"}"""))
        assertEquals(PhoneControlCommand.Status, parse("""{"type":"phone.status.request"}"""))
        assertEquals(PhoneControlCommand.Ringer("silent"), parse("""{"type":"phone.ringer","mode":"silent"}"""))
        assertEquals(PhoneControlCommand.Dnd(true), parse("""{"type":"phone.dnd","active":true}"""))
        assertEquals(PhoneControlCommand.Media("org.example.player", "next"), parse("""{"type":"media.command","source":"org.example.player","action":"next"}"""))
        assertEquals(PhoneControlCommand.MobileData(false), parse("""{"type":"phone.mobile_data","allowed":false}"""))
        assertEquals(PhoneControlCommand.Hotspot, parse("""{"type":"phone.hotspot"}"""))
        assertEquals(PhoneControlCommand.Wallpaper, parse("""{"type":"phone.wallpaper.request"}"""))
        for (bad in listOf("""{"type":"phone.ring","loud":true}""", """{"type":"phone.ringer","mode":"loud"}""",
                """{"type":"phone.dnd","active":"yes"}""", """{"type":"media.command","source":"","action":"play"}""",
                """{"type":"media.command","source":"org.example.player","action":"seek"}""",
                """{"type":"phone.mobile_data","allowed":1}""", """{"type":"phone.unknown"}"""))
            assertNull(bad, parse(bad))
    }

    @Test fun ringStateMatchesTheDesktopWireShape() {
        // tests/test_phone_status_shared.py reads the same literals.
        val ringing = FindPhoneRing.State.Ringing("Desk", 31_000)
        assertEquals("""{"ringing":true,"seconds":30,"type":"phone.ring.state"}""", canonical(PhoneStatusFrames.ringState(ringing, 1_000)))
        assertEquals("""{"ringing":false,"seconds":0,"type":"phone.ring.state"}""", canonical(PhoneStatusFrames.ringState(FindPhoneRing.State.Idle, 1_000)))
        assertEquals("""{"ringing":true,"seconds":1}""", canonical(PhoneStatusFrames.ringStateBody(ringing, 31_000)))
        // Never more than the desktop believes, never 0 while ringing.
        assertEquals(120, PhoneStatusFrames.ringStateBody(FindPhoneRing.State.Ringing(null, 999_000), 0).getValue("seconds").jsonPrimitive.int)
        assertEquals(JsonObject(PhoneStatusFrames.ringState(ringing, 0) - "type"), PhoneStatusFrames.ringStateBody(ringing, 0))
    }

    @Test fun computersStopTheRingWithTheRingControl() {
        fun parse(json: String) = PhoneStatusFrames.command(Json.parseToJsonElement(json).jsonObject)
        assertEquals(PhoneControlCommand.RingStop, parse("""{"type":"phone.ring.stop"}"""))
        assertNull(parse("""{"type":"phone.ring.stop","now":true}"""))
        assertTrue(PhoneStatusFrames.allowed("phone.ring.stop", "desk", setOf("desk"), controls))
        assertFalse(PhoneStatusFrames.allowed("phone.ring.stop", "desk", setOf("desk"), controls - "ring"))
        // Hub phones take it through the shared layer, unlike the older phone.ring path.
        val link = PhoneStatusFrames.controls(true, true, true, false, PhoneTransport.LINK)
        assertEquals(PhoneControlCommand.RingStop, PhoneStatusFrames.linkCommand("phone.ring.stop", JsonObject(emptyMap()), link))
        // Listing "ring" still names the control once; no new control name reaches older desktops.
        assertEquals(controls, PhoneStatusFrames.body(status()).getValue("controls").jsonArray.map { it.jsonPrimitive.content })
    }

    @Test fun wallpaperBodyIsTheCloudPayloadWithoutItsType() {
        val jpeg = byteArrayOf(-1, -40, 1, 2, -1, -39)
        assertEquals("""{"preview":"data:image/jpeg;base64,/9gBAv/Z"}""", canonical(PhoneStatusFrames.wallpaperBody(jpeg)))
        assertEquals(JsonObject(PhoneStatusFrames.wallpaper(jpeg) - "type"), PhoneStatusFrames.wallpaperBody(jpeg))
    }

    @Test fun wallpaperIsASmallJpegOrEmpty() {
        assertEquals("", PhoneStatusFrames.wallpaper(null).getValue("preview").jsonPrimitive.content)
        assertEquals("", PhoneStatusFrames.wallpaper(ByteArray(12_001)).getValue("preview").jsonPrimitive.content)
        val jpeg = byteArrayOf(-1, -40, 1, 2, -1, -39)
        assertEquals("data:image/jpeg;base64,/9gBAv/Z", PhoneStatusFrames.wallpaper(jpeg).getValue("preview").jsonPrimitive.content)
    }

    @Test fun hubPhonesSendTheSameStatusWithoutCloudOnlyControls() {
        assertEquals(listOf("status", "ring", "ringer", "dnd", "media", "wallpaper", "hotspot"), PhoneStatusFrames.controls(true, true, true, true, PhoneTransport.LINK))
        val link = PhoneStatusFrames.controls(true, true, true, false, PhoneTransport.LINK)
        assertEquals(listOf("status", "ring", "ringer", "dnd", "media", "hotspot"), link)
        val body = PhoneStatusFrames.body(status().copy(controls = link))
        assertEquals(LINK_STATUS_WIRE, canonical(body))
        // The Cloud payload is the same body with its type inside.
        assertEquals(JsonObject(PhoneStatusFrames.payload(status().copy(controls = link)) - "type"), body)
        assertEquals(emptyList<String>(), PhoneStatusFrames.controls(false, true, true, true, PhoneTransport.LINK))
    }

    @Test fun hubQuickActionsRunOnlyWhenListedAndExact() {
        val link = PhoneStatusFrames.controls(true, true, true, false, PhoneTransport.LINK)
        fun body(json: String) = Json.parseToJsonElement(json).jsonObject
        assertEquals(PhoneControlCommand.Dnd(true), PhoneStatusFrames.linkCommand("phone.dnd", body("""{"active":true}"""), link))
        assertEquals(PhoneControlCommand.Hotspot, PhoneStatusFrames.linkCommand("phone.hotspot", body("{}"), link))
        assertEquals(PhoneControlCommand.Status, PhoneStatusFrames.linkCommand("phone.status.request", body("{}"), link))
        // Without Do Not Disturb access the phone does not list "dnd"; a body with a type inside is a Cloud shape.
        assertNull(PhoneStatusFrames.linkCommand("phone.dnd", body("""{"active":true}"""), PhoneStatusFrames.controls(true, false, true, false, PhoneTransport.LINK)))
        assertNull(PhoneStatusFrames.linkCommand("phone.dnd", body("""{"type":"phone.dnd","active":true}"""), link))
        // The wallpaper only when this phone can read it and lists it.
        assertNull(PhoneStatusFrames.linkCommand("phone.wallpaper.request", body("{}"), link))
        assertEquals(PhoneControlCommand.Wallpaper, PhoneStatusFrames.linkCommand("phone.wallpaper.request", body("{}"), link + "wallpaper"))
        // Ring, ringer and media keep the older Hub path; Sync over mobile data is not carried by the Hub.
        for (type in listOf("phone.ring", "phone.ringer", "media.command", "phone.mobile_data"))
            assertNull(type, PhoneStatusFrames.linkCommand(type, body("{}"), link + listOf("mobile_data")))
    }

    @Test fun publisherSendsTheSameWayOverBothTransports() {
        val publisher = PhoneStatusPublisher()
        val sent = mutableListOf<String>()
        val hub = setOf(PhoneStatusPublisher.BROADCAST)
        assertEquals(hub, publisher.sync(hub, status(), false, 1_000) { sent += it; true })
        // Unchanged and not due: nothing; a missed (unqueued) send is retried on the next pass.
        assertEquals(emptySet<String>(), publisher.sync(hub, status(), false, 2_000) { sent += it; true })
        assertEquals(emptySet<String>(), publisher.sync(hub, status(ringer = "silent"), false, 3_000) { false })
        assertEquals(hub, publisher.sync(hub, status(ringer = "silent"), false, 4_000) { sent += it; true })
        // Refresh: once per computer every ten seconds, and only that computer gets it again (Cloud).
        val cloud = setOf("desk", "laptop")
        val fresh = PhoneStatusPublisher()
        fresh.sync(cloud, status(), false, 1_000) { true }
        assertTrue(fresh.refresh("desk", "desk", 2_000))
        assertFalse(fresh.refresh("desk", "desk", 5_000))
        assertEquals(setOf("desk"), fresh.sync(cloud, status(), false, 6_000) { true })
        // A new computer gets the status without resending to the others; a pause goes to all.
        assertEquals(setOf("phone-2"), fresh.sync(cloud + "phone-2", status(), false, 7_000) { true })
        assertEquals(cloud, fresh.sync(cloud, status(), true, 8_000) { true })
    }

    @Test fun signalBarsTravelInTheirOwnEventSoOlderPeersKeepTheStatus() {
        assertEquals(SIGNAL_WIRE, canonical(PhoneStatusFrames.signalPayload(status())))
        assertEquals(LINK_SIGNAL_WIRE, canonical(PhoneStatusFrames.signalBody(PhoneStatusFrames.hidden(mobileData = true, paused = false))))
        assertEquals(4, PhoneStatusFrames.signalBody(status(wifiLevel = 9)).getValue("wifi_level").jsonPrimitive.int)
        // phone.status itself is unchanged, so older desktops and Hubs still accept it.
        assertEquals(STATUS_WIRE, canonical(PhoneStatusFrames.payload(status(wifiLevel = 0, cellularLevel = 0))))
    }

    @Test fun barsFollowAndroidsScale() {
        assertEquals(listOf(0, 1, 2, 3, 4), (0..4).map { PhoneStatusFrames.bars(it, 4) })
        assertEquals(listOf(0, 1, 2, 2, 3, 4), (0..5).map { PhoneStatusFrames.bars(it, 5) })
        assertNull(PhoneStatusFrames.bars(-1, 4)); assertNull(PhoneStatusFrames.bars(2, 0))
    }
}
