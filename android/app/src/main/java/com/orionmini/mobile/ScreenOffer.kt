// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import kotlinx.serialization.json.*
import java.util.Base64

/**
 * A one-use phone screen invitation (`orion-screen:1:`), scanned from the computer's QR or
 * carried as the `invite` of a sealed [SessionOffer] with service "screen". The desktop's
 * `session_offer.screen_invite` applies the same checks. Never put its secret in URLs,
 * logs, saved state or intents.
 */
internal class ScreenOffer(val session: String, val addresses: List<String>, val port: Int,
    val certificate: String, val secret: String, val expires: Long, val launch: String,
    val resolution: String, val fps: Int, val quality: String) {
    /** Longest side and pixel budget of the frames this offer allows. */
    val maxSide get() = if (resolution == "1080p") 1920 else 1280
    val maxPixels get() = if (resolution == "1080p") 1920 * 1080 else 1280 * 720
    val jpegQuality get() = if (quality == "high") 85 else 70

    companion object {
        const val PREFIX = "orion-screen:1:"
        private val PACKAGE = Regex("[A-Za-z][A-Za-z0-9_]*(\\.[A-Za-z][A-Za-z0-9_]*)+")
        private val KEYS = setOf("session", "addresses", "port", "certificate", "secret", "expires", "stream", "launch")
        fun validPackage(value: String) = value.length <= 200 && PACKAGE.matches(value)

        fun parse(code: String, now: Long = System.currentTimeMillis() / 1000): ScreenOffer {
            require(code.length in 100..2048 && code.startsWith(PREFIX)) { "Scan a new code from Saiph on your computer." }
            val encoded = code.removePrefix(PREFIX)
            require(Regex("[A-Za-z0-9_-]+").matches(encoded))
            val value = Json.parseToJsonElement(Base64.getUrlDecoder().decode(encoded).toString(Charsets.UTF_8)).jsonObject
            require(value.keys == KEYS)
            fun text(source: JsonObject, key: String) = source.getValue(key).jsonPrimitive.let { require(it.isString); it.content }
            fun number(source: JsonObject, key: String) = source.getValue(key).jsonPrimitive.let {
                require(!it.isString && it.booleanOrNull == null); it.content.toLong()
            }
            val session = text(value, "session"); val certificate = text(value, "certificate"); val secret = text(value, "secret")
            require(Regex("[a-f0-9]{32}").matches(session) && Regex("[a-f0-9]{64}").matches(certificate))
            require(Regex("[A-Za-z0-9_-]{43}").matches(secret) && Base64.getUrlDecoder().decode(secret).size == 32)
            val addresses = value.getValue("addresses").jsonArray.map { it.jsonPrimitive.let { item -> require(item.isString); item.content } }
            require(addresses.size in 1..8 && addresses.distinct().size == addresses.size && addresses.all(CameraOffer::localAddress))
            val port = number(value, "port"); val expires = number(value, "expires")
            require(port in 1024..65535 && expires > now && expires <= now + SessionOffer.MAX_LIFETIME)
            val launch = text(value, "launch")
            require(launch.isEmpty() || validPackage(launch))
            val stream = value.getValue("stream").jsonObject
            require(stream.keys == setOf("resolution", "fps", "quality"))
            val resolution = text(stream, "resolution"); val fps = number(stream, "fps"); val quality = text(stream, "quality")
            require(resolution in setOf("720p", "1080p") && fps in setOf(15L, 20L, 30L) && quality in setOf("standard", "high"))
            return ScreenOffer(session, addresses, port.toInt(), certificate, secret, expires, launch, resolution, fps.toInt(), quality)
        }
    }
}
