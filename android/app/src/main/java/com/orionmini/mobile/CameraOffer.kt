// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import kotlinx.serialization.json.*
import java.util.Base64

/** One-use local capability. Never put its secret in URLs, logs or saved state. */
internal class CameraOffer(val session: String, val addresses: List<String>, val port: Int,
    val certificate: String, val secret: String, val expires: Long,
    val resolution: String = "720p", val fps: Int = 15, val quality: String = "standard") {
    val width get() = if (resolution == "1080p") 1920 else 1280
    val height get() = if (resolution == "1080p") 1080 else 720
    val jpegQuality get() = if (quality == "high") 90 else 75
    companion object {
        const val PREFIX = "orion-camera:1:"
        const val PROFILE_PREFIX = "orion-camera:2:"
        fun localAddress(value: String): Boolean {
            if (!Regex("[0-9]{1,3}(\\.[0-9]{1,3}){3}").matches(value)) return false
            val parts = value.split('.').map(String::toInt)
            if (parts.any { it !in 0..255 } || parts.joinToString(".") != value) return false
            return parts[0] == 10 || (parts[0] == 172 && parts[1] in 16..31) || (parts[0] == 192 && parts[1] == 168)
        }
        fun parse(code: String, now: Long = System.currentTimeMillis() / 1000): CameraOffer {
            val profiled = code.startsWith(PROFILE_PREFIX)
            val prefix = if (profiled) PROFILE_PREFIX else PREFIX
            require(code.length in 100..2048 && code.startsWith(prefix)) { "Scan a new camera code from Saiph on your computer." }
            val encoded = code.removePrefix(prefix)
            require(Regex("[A-Za-z0-9_-]+").matches(encoded))
            val value = Json.parseToJsonElement(Base64.getUrlDecoder().decode(encoded).toString(Charsets.UTF_8)).jsonObject
            val keys = setOf("session", "addresses", "port", "certificate", "secret", "expires")
            require(value.keys == if (profiled) keys + "stream" else keys)
            fun text(key: String) = value.getValue(key).jsonPrimitive.let { require(it.isString); it.content }
            val session = text("session"); val certificate = text("certificate"); val secret = text("secret")
            require(Regex("[a-f0-9]{32}").matches(session) && Regex("[a-f0-9]{64}").matches(certificate))
            require(Regex("[A-Za-z0-9_-]{43}").matches(secret) && Base64.getUrlDecoder().decode(secret).size == 32)
            val addresses = value.getValue("addresses").jsonArray.map { it.jsonPrimitive.let { item -> require(item.isString); item.content } }
            require(addresses.size in 1..8 && addresses.distinct().size == addresses.size && addresses.all(::localAddress))
            val port = value.getValue("port").jsonPrimitive.let { require(!it.isString); it.int }
            val expires = value.getValue("expires").jsonPrimitive.let { require(!it.isString); it.long }
            require(port in 1024..65535 && expires > now && expires <= now + 120)
            var resolution = "720p"; var fps = 15; var quality = "standard"
            if (profiled) {
                val stream = value.getValue("stream").jsonObject
                require(stream.keys == setOf("resolution", "fps", "quality"))
                resolution = stream.getValue("resolution").jsonPrimitive.let { require(it.isString); it.content }
                fps = stream.getValue("fps").jsonPrimitive.let { require(!it.isString); it.int }
                quality = stream.getValue("quality").jsonPrimitive.let { require(it.isString); it.content }
                require(resolution in setOf("720p", "1080p") && fps in setOf(15, 20, 30) && quality in setOf("standard", "high"))
            }
            return CameraOffer(session, addresses, port, certificate, secret, expires, resolution, fps, quality)
        }
    }
}
