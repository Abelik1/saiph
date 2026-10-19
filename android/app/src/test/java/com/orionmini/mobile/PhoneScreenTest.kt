// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import java.nio.ByteBuffer
import java.util.Base64
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import sefirah.network.orion.HostedPhoneFrames

/** Phone screen offers, the screen socket protocol and the Cloud app list (docs/PHONE_SCREEN.md). Synthetic values only. */
class PhoneScreenTest {
    private val now = 1800000000L
    /** Produced by the desktop's session_offer.encode for the same synthetic values. */
    private val desktop = "orion-screen:1:eyJhZGRyZXNzZXMiOlsiMTkyLjE2OC4xLjciLCIxMC4wLjAuNSJdLCJjZXJ0aWZpY2F0ZSI6ImJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmIiLCJleHBpcmVzIjoxODAwMDAwMDYwLCJsYXVuY2giOiJjb20uZXhhbXBsZS5zeW50aGV0aWMiLCJwb3J0Ijo0OTE5Miwic2VjcmV0IjoiQXdNREF3TURBd01EQXdNREF3TURBd01EQXdNREF3TURBd01EQXdNREF3TSIsInNlc3Npb24iOiJhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYSIsInN0cmVhbSI6eyJmcHMiOjMwLCJxdWFsaXR5Ijoic3RhbmRhcmQiLCJyZXNvbHV0aW9uIjoiNzIwcCJ9fQ"

    private fun offer(change: (MutableMap<String, JsonElement>) -> Unit = {}): String {
        val value = mutableMapOf<String, JsonElement>("session" to JsonPrimitive("a".repeat(32)),
            "addresses" to JsonArray(listOf(JsonPrimitive("192.168.1.7"))), "port" to JsonPrimitive(49192),
            "certificate" to JsonPrimitive("b".repeat(64)), "secret" to JsonPrimitive(Base64.getUrlEncoder().withoutPadding().encodeToString(ByteArray(32) { 3 })),
            "expires" to JsonPrimitive(now + 120), "launch" to JsonPrimitive(""),
            "stream" to buildJsonObject { put("resolution", "1080p"); put("fps", 20); put("quality", "high") })
        change(value)
        return ScreenOffer.PREFIX + Base64.getUrlEncoder().withoutPadding().encodeToString(JsonObject(value).toString().toByteArray())
    }
    private fun rejects(change: (MutableMap<String, JsonElement>) -> Unit) =
        assertTrue(runCatching { ScreenOffer.parse(offer(change), now) }.isFailure)

    @Test fun desktopOfferParsesWithItsProfileAndLaunch() {
        val value = ScreenOffer.parse(desktop, now)
        assertEquals(listOf("192.168.1.7", "10.0.0.5"), value.addresses)
        assertEquals("com.example.synthetic", value.launch)
        assertEquals(Triple("720p", 30, "standard"), Triple(value.resolution, value.fps, value.quality))
        assertEquals(1280, value.maxSide)
        assertTrue(runCatching { ScreenOffer.parse(desktop, now + 60) }.isFailure)
    }

    @Test fun offerRefusesPublicExpiredOrUnknownValues() {
        assertEquals(1920, ScreenOffer.parse(offer(), now).maxSide)
        rejects { it["addresses"] = JsonArray(listOf(JsonPrimitive("8.8.8.8"))) }
        rejects { it["expires"] = JsonPrimitive(now + 121) }
        rejects { it["launch"] = JsonPrimitive("not a package") }
        rejects { it["stream"] = buildJsonObject { put("resolution", "4k"); put("fps", 20); put("quality", "high") } }
        rejects { it["stream"] = buildJsonObject { put("resolution", "1080p"); put("fps", 60); put("quality", "high") } }
        rejects { it.remove("launch") }
        rejects { it["extra"] = JsonPrimitive(true) }
        assertTrue(runCatching { ScreenOffer.parse(CameraOffer.PROFILE_PREFIX + offer().removePrefix(ScreenOffer.PREFIX), now) }.isFailure)
    }

    @Test fun screenInvitationsRideInTheSharedSessionOffer() {
        val code = offer()
        fun event(service: String = "screen", expires: Long = now + 120, extra: Boolean = false) = buildJsonObject {
            put("type", "session.offer"); put("version", 1); put("id", "c".repeat(32)); put("service", service)
            put("expires_at", expires); put("invite", code); if (extra) put("secret", "x")
        }
        val parsed = SessionOffer.parse(event(), now)
        assertEquals("screen", parsed.service)
        assertEquals(1920, parsed.screen.maxSide)
        assertTrue(runCatching { parsed.camera }.isFailure)
        assertTrue(runCatching { SessionOffer.parse(event(service = "camera"), now) }.isFailure)
        assertTrue(runCatching { SessionOffer.parse(event(expires = now + 60), now) }.isFailure)
        assertTrue(runCatching { SessionOffer.parse(event(extra = true), now) }.isFailure)
    }

    @Test fun requestsAreExactAndBounded() {
        assertEquals(ScreenRequest.Tap(5000, 10000, false), ScreenProtocol.request("""{"t":"tap","x":5000,"y":10000}"""))
        assertEquals(ScreenRequest.Tap(1, 2, true), ScreenProtocol.request("""{"t":"long","x":1,"y":2}"""))
        assertEquals(ScreenRequest.Swipe(1, 2, 3, 4, 300), ScreenProtocol.request("""{"t":"swipe","x":1,"y":2,"x2":3,"y2":4,"ms":300}"""))
        assertEquals(ScreenRequest.Key("recents"), ScreenProtocol.request("""{"t":"key","key":"recents"}"""))
        assertEquals(ScreenRequest.Text("Synthetic ✓"), ScreenProtocol.request("""{"t":"text","text":"Synthetic ✓"}"""))
        assertEquals(ScreenRequest.Launch("com.example.app"), ScreenProtocol.request("""{"t":"launch","package":"com.example.app"}"""))
        assertEquals(ScreenRequest.Apps, ScreenProtocol.request("""{"t":"apps"}"""))
        for (bad in listOf("""{"t":"tap","x":10001,"y":0}""", """{"t":"tap","x":-1,"y":0}""", """{"t":"tap","x":1.5,"y":0}""",
            """{"t":"tap","x":"1","y":0}""", """{"t":"tap","x":1,"y":1,"z":1}""", """{"t":"swipe","x":1,"y":2,"x2":3,"y2":4,"ms":10}""",
            """{"t":"key","key":"power"}""", """{"t":"text","text":""}""", """{"t":"text","text":"a\nb"}""",
            """{"t":"text","text":"${"x".repeat(257)}"}""", """{"t":"launch","package":"evil;rm"}""", """{"t":"shell","cmd":"id"}""", "[]", "not json"))
            assertNull(bad, ScreenProtocol.request(bad))
    }

    @Test fun framesUseTheScreenHeaderAndCaptureFitsTheProfile() {
        val jpeg = byteArrayOf(-1, -40, 1, 2, -1, -39)
        val frame = ByteBuffer.wrap(ScreenProtocol.frame(jpeg, 540, 1170, 7))
        assertEquals("SSF1", String(ByteArray(4).also { frame.get(it) }))
        assertEquals(540, frame.short.toInt()); assertEquals(1170, frame.short.toInt()); assertEquals(0, frame.short.toInt())
        assertEquals(7L, frame.long)
        // A 1080×2400 portrait phone: within the longest side and pixel budget, even and upright.
        val (w, h) = ScreenProtocol.captureSize(1080, 2400, 1920, 1920 * 1080)
        assertTrue(maxOf(w, h) <= 1920 && w * h <= 1920 * 1080 && w % 2 == 0 && h % 2 == 0 && h > w)
        val (w7, h7) = ScreenProtocol.captureSize(1080, 2400, 1280, 1280 * 720)
        assertTrue(maxOf(w7, h7) <= 1280 && w7 * h7 <= 1280 * 720)
        assertEquals(720 to 1280, ScreenProtocol.captureSize(720, 1280, 1920, 1920 * 1080))
        assertEquals(0f, ScreenProtocol.pixel(0, 1080)); assertEquals(1079f, ScreenProtocol.pixel(10000, 1080))
    }

    @Test fun textEditsFollowTheSelectionWithoutSplittingPairs() {
        assertEquals("helloX world" to 6, ScreenProtocol.edit("hello world", 5, 5, "X"))
        assertEquals("hi" to 2, ScreenProtocol.edit("", -1, -1, "hi"))
        assertEquals("h world" to 1, ScreenProtocol.edit("hello world", 1, 5, null))
        assertEquals("a" to 1, ScreenProtocol.edit("a😀", 3, 3, null))
        assertEquals("" to 0, ScreenProtocol.edit("", 0, 0, null))
        assertEquals("ab" to 2, ScreenProtocol.edit("a", 9, 9, "b"))
    }

    @Test fun appListsAreCleanAndPagedToFitSealedEvents() {
        val apps = List(400) { "com.example.app$it" to "Synthetic app $it ${"✓".repeat(40)}" } +
            listOf("bad package" to "Bad", "com.example.empty" to "\u0000 ", "com.example.app0" to "Duplicate")
        val rows = ScreenProtocol.appRows(apps)
        assertEquals(401, rows.size)
        assertEquals("com.example.empty", rows.last().jsonObject.getValue("name").jsonPrimitive.content)
        assertTrue(rows.all { it.jsonObject.getValue("name").jsonPrimitive.content.length in 1..80 })
        val pages = HostedPhoneFrames.appsPages(rows)
        assertTrue(pages.size in 2..10)
        assertTrue(pages.all(HostedPhoneFrames::fits))
        assertEquals(401, pages.sumOf { it.getValue("apps").jsonArray.size })
        pages.forEachIndexed { index, page ->
            assertEquals(index, page.getValue("page").jsonPrimitive.int); assertEquals(pages.size, page.getValue("pages").jsonPrimitive.int)
        }
        assertTrue(HostedPhoneFrames.appsRequest(buildJsonObject { put("type", "apps.request") }))
        assertFalse(HostedPhoneFrames.appsRequest(buildJsonObject { put("type", "apps.request"); put("all", true) }))
    }

    @Test fun screenCommandsNeedASubscriberAndTheOwnerSwitch() {
        val subscribers = setOf("dev_computer")
        assertTrue(HostedPhoneFrames.screenAllowed("apps.request", "dev_computer", subscribers, true))
        assertFalse(HostedPhoneFrames.screenAllowed("apps.request", "dev_other", subscribers, true))
        assertFalse(HostedPhoneFrames.screenAllowed("apps.request", "dev_computer", subscribers, false))
        // Offers use the shared session.offer event (SessionOffer.TYPE), not this table.
        assertFalse(HostedPhoneFrames.screenAllowed("session.offer", "dev_computer", subscribers, true))
        assertFalse(HostedPhoneFrames.screenAllowed("sms.send", "dev_computer", subscribers, true))
        assertEquals(emptyList<String>(), HostedPhoneFrames.screenCapabilities(false))
        assertEquals("screen.capabilities", HostedPhoneFrames.screenCapabilitiesPayload(listOf("screen")).getValue("type").jsonPrimitive.content)
        // Older desktops reject unknown names here, so screen support never appears in phone.capabilities.
        assertFalse("screen" in HostedPhoneFrames.COMMAND_CAPABILITY.values || "apps" in HostedPhoneFrames.DATA_CAPABILITY.values)
    }
}
