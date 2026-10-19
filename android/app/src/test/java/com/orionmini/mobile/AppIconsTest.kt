// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import java.util.Base64
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import sefirah.network.orion.HostedPhoneFrames

/** App icons for the computer's Apps grid: request shape, size bounds and sealed-event paging. */
class AppIconsTest {
    private fun request(vararg rows: Pair<String, Long>) = buildJsonObject {
        put("type", "apps.icons.request")
        put("apps", JsonArray(rows.map { (name, version) -> buildJsonObject { put("package", name); put("version", version) } }))
    }

    @Test fun requestsAreExactAndBounded() {
        assertEquals(listOf(AppIcons.Want("com.example.mail", 0), AppIcons.Want("com.example.maps", 42)),
            AppIcons.request(request("com.example.mail" to 0L, "com.example.maps" to 42L)))
        assertNull(AppIcons.request(request()))
        assertNull(AppIcons.request(request("com.example.mail" to 1L, "com.example.mail" to 2L)))
        assertNull(AppIcons.request(request("not a package" to 1L)))
        assertNull(AppIcons.request(request("com.example.mail" to -1L)))
        assertNull(AppIcons.request(request(*Array(25) { "com.example.app$it" to 0L })))
        assertNull(AppIcons.request(JsonObject(request("com.example.mail" to 0L) + ("extra" to JsonPrimitive(1)))))
        val stringVersion = buildJsonObject { put("type", "apps.icons.request")
            put("apps", buildJsonArray { add(buildJsonObject { put("package", "com.example.mail"); put("version", "3") }) }) }
        assertNull(AppIcons.request(stringVersion))
    }

    @Test fun encodingTriesSmallerImagesUntilOneFits() {
        val tried = mutableListOf<Pair<Int, Int>>()
        val result = AppIcons.bounded { side, quality -> tried += side to quality; ByteArray(if (side >= 96) 20_000 else 9_000) }
        assertEquals(9_000, result?.size)
        assertEquals(listOf(96 to 85, 96 to 70, 80 to 60), tried)
        assertNull(AppIcons.bounded { _, _ -> ByteArray(AppIcons.MAX_BYTES + 1) })
        assertNull(AppIcons.bounded { _, _ -> throw IllegalStateException() })
        assertNull(AppIcons.bounded { _, _ -> ByteArray(10) })
    }

    @Test fun unchangedUnlistedOrUnencodableAppsSendNothingNew() {
        var encoded = 0
        val encode = { encoded++; ByteArray(3000) { 1 } }
        assertNull(AppIcons.decide(AppIcons.Want("com.example.mail", 7), listed = true, version = 7, encode = encode).data)
        assertNull(AppIcons.decide(AppIcons.Want("com.example.gone", 0), listed = false, version = 1, encode = encode).data)
        assertNull(AppIcons.decide(AppIcons.Want("com.example.gone", 0), listed = true, version = null, encode = encode).data)
        assertEquals(0, encoded)
        val updated = AppIcons.decide(AppIcons.Want("com.example.mail", 7), listed = true, version = 8, encode = encode)
        assertEquals(8L, updated.version); assertEquals(3000, updated.data?.size)
        assertEquals(3000, AppIcons.decide(AppIcons.Want("com.example.new", 0), listed = true, version = 0, encode = encode).data?.size)
    }

    @Test fun answersFitSealedEventsAndListEachAppOnce() {
        val icons = (0 until 20).map { AppIcons.Icon("com.example.app$it", it.toLong(), ByteArray(AppIcons.MAX_BYTES) { b -> b.toByte() }) } +
            AppIcons.Icon("com.example.same", 3, null)
        val events = AppIcons.answers(icons)
        assertTrue(events.size >= 10)  // 12,000-byte icons: at most one per 20,000-byte event.
        events.forEach { event ->
            assertTrue(HostedPhoneFrames.fits(event))
            assertEquals(setOf("type", "icons", "same"), event.keys)
            assertEquals("apps.icons", event.getValue("type").jsonPrimitive.content)
        }
        assertEquals(listOf("com.example.same"), events.first().getValue("same").jsonArray.map { it.jsonPrimitive.content })
        val sent = events.flatMap { it.getValue("icons").jsonArray }.map { it.jsonObject }
        assertEquals(20, sent.size)
        assertEquals((0 until 20).map { "com.example.app$it" }, sent.map { it.getValue("package").jsonPrimitive.content })
        assertArrayEquals(ByteArray(AppIcons.MAX_BYTES) { b -> b.toByte() }, Base64.getDecoder().decode(sent[0].getValue("data").jsonPrimitive.content))
        // Small icons share events, up to 24 rows each.
        val small = AppIcons.answers((0 until 24).map { AppIcons.Icon("com.example.s$it", 1, ByteArray(400)) })
        assertTrue(small.size in 1..2)
        assertTrue(AppIcons.answers(emptyList()).isEmpty())
    }

    @Test fun eachComputerIsRateLimited() {
        val source = "dev_rate_" + System.nanoTime()
        repeat(12) { assertTrue(AppIcons.allow(source, 1_000L + it)) }
        assertFalse(AppIcons.allow(source, 2_000L))
        assertTrue(AppIcons.allow(source, 62_000L))
    }

    @Test fun iconRequestsNeedTheAppsPermissionLikeAppLists() {
        assertTrue(HostedPhoneFrames.screenAllowed("apps.icons.request", "dev_a", setOf("dev_a"), allowed = true))
        assertFalse(HostedPhoneFrames.screenAllowed("apps.icons.request", "dev_a", setOf("dev_a"), allowed = false))
        assertFalse(HostedPhoneFrames.screenAllowed("apps.icons.request", "dev_b", setOf("dev_a"), allowed = true))
    }
}
