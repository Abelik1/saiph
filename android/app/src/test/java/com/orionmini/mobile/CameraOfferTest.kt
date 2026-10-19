// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import java.util.Base64
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class CameraOfferTest {
    private val now = 1800000000L
    private fun offer(change: (MutableMap<String, JsonElement>) -> Unit = {}): String {
        val value = mutableMapOf<String, JsonElement>("session" to JsonPrimitive("a".repeat(32)),
            "addresses" to JsonArray(listOf(JsonPrimitive("192.168.1.7"))), "port" to JsonPrimitive(49192),
            "certificate" to JsonPrimitive("b".repeat(64)), "secret" to JsonPrimitive(Base64.getUrlEncoder().withoutPadding().encodeToString(ByteArray(32) { 3 })),
            "expires" to JsonPrimitive(now + 120))
        change(value)
        return CameraOffer.PREFIX + Base64.getUrlEncoder().withoutPadding().encodeToString(JsonObject(value).toString().toByteArray())
    }
    private fun rejects(change: (MutableMap<String, JsonElement>) -> Unit) {
        assertTrue(runCatching { CameraOffer.parse(offer(change), now) }.isFailure)
    }
    @Test fun localCapabilityIsBoundedAndExpires() {
        val value = CameraOffer.parse(offer(), now)
        assertEquals(listOf("192.168.1.7"), value.addresses)
        assertEquals(49192, value.port)
        rejects { it["expires"] = JsonPrimitive(now) }
        rejects { it["expires"] = JsonPrimitive(now + 121) }
        rejects { it["port"] = JsonPrimitive(443) }
        rejects { it["port"] = JsonPrimitive("49192") }
    }
    @Test fun noPublicLoopbackDnsOrAmbiguousAddresses() {
        for (address in listOf("127.0.0.1", "8.8.8.8", "169.254.169.254", "localhost", "192.168.001.7", "10.0.0.999", "[::1]"))
            rejects { it["addresses"] = JsonArray(listOf(JsonPrimitive(address))) }
        rejects { it["addresses"] = JsonArray(emptyList()) }
        rejects { it["addresses"] = JsonArray(List(2) { JsonPrimitive("10.0.0.1") }) }
    }
    @Test fun rejectsExtraFieldsAndBadCredentials() {
        rejects { it["account_token"] = JsonPrimitive("synthetic") }
        rejects { it["secret"] = JsonPrimitive("x".repeat(42)) }
        rejects { it["certificate"] = JsonPrimitive("g".repeat(64)) }
        rejects { it["session"] = JsonPrimitive("a".repeat(31)) }
        assertTrue(runCatching { CameraOffer.parse("orion://pair/synthetic", now) }.isFailure)
    }
    @Test fun acceptsBoundedV2ProfilesAndRetainsV1Defaults() {
        val legacy = CameraOffer.parse(offer(), now)
        assertEquals(15, legacy.fps); assertEquals(1280, legacy.width)
        fun profile(resolution: JsonElement = JsonPrimitive("1080p"), fps: JsonElement = JsonPrimitive(20),
            quality: JsonElement = JsonPrimitive("high")): String = offer {
            it["stream"] = buildJsonObject { put("resolution", resolution); put("fps", fps); put("quality", quality) }
        }.replaceFirst(CameraOffer.PREFIX, CameraOffer.PROFILE_PREFIX)
        val current = CameraOffer.parse(profile(), now)
        assertEquals(1920, current.width); assertEquals(1080, current.height)
        assertEquals(20, current.fps); assertEquals(90, current.jpegQuality)
        for (invalid in listOf(profile(fps = JsonPrimitive(120)), profile(fps = JsonPrimitive("20")),
            profile(resolution = JsonPrimitive("4k")), profile(quality = JsonPrimitive("lossless"))))
            assertTrue(runCatching { CameraOffer.parse(invalid, now) }.isFailure)
        assertTrue(runCatching { CameraOffer.parse(profile().replaceFirst(CameraOffer.PROFILE_PREFIX, CameraOffer.PREFIX), now) }.isFailure)
        assertTrue(runCatching { CameraOffer.parse(offer().replaceFirst(CameraOffer.PREFIX, CameraOffer.PROFILE_PREFIX), now) }.isFailure)
    }
}
