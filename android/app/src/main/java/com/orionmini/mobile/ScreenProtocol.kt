// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import kotlinx.serialization.json.*
import sefirah.network.orion.HostedPhoneFrames
import java.nio.ByteBuffer

/** One computer request on a live phone screen socket, after exact-shape validation. */
internal sealed interface ScreenRequest {
    data class Tap(val x: Int, val y: Int, val long: Boolean) : ScreenRequest
    data class Swipe(val x: Int, val y: Int, val x2: Int, val y2: Int, val ms: Int) : ScreenRequest
    data class Key(val key: String) : ScreenRequest
    data class Text(val text: String) : ScreenRequest
    data class Launch(val packageName: String) : ScreenRequest
    data object Apps : ScreenRequest
}

/**
 * The phone side of the desktop's `screen_session.py`. Pure, so the JVM tests cover it.
 * Frames are SSF1: magic, 16-bit width, height and rotation (always 0: the projection is
 * already upright) and a 64-bit sequence, all network order, followed by one JPEG.
 */
internal object ScreenProtocol {
    const val SCALE = 10_000
    const val MAX_FRAME = 1_500_000
    val KEYS = setOf("back", "home", "recents", "backspace", "enter")
    private val MAGIC = byteArrayOf(83, 83, 70, 49) // "SSF1"

    fun request(text: String): ScreenRequest? = runCatching {
        require(text.length <= 4096)
        val value = Json.parseToJsonElement(text).jsonObject
        fun keys(vararg names: String) = require(value.keys == setOf("t", *names))
        fun string(key: String) = value.getValue(key).jsonPrimitive.let { require(it.isString); it.content }
        fun integer(key: String, low: Int = 0, high: Int = SCALE): Int = value.getValue(key).jsonPrimitive.let {
            require(!it.isString && Regex("0|[1-9][0-9]{0,4}").matches(it.content)); it.content.toInt().also { n -> require(n in low..high) }
        }
        when (string("t")) {
            "tap" -> { keys("x", "y"); ScreenRequest.Tap(integer("x"), integer("y"), false) }
            "long" -> { keys("x", "y"); ScreenRequest.Tap(integer("x"), integer("y"), true) }
            "swipe" -> { keys("x", "y", "x2", "y2", "ms"); ScreenRequest.Swipe(integer("x"), integer("y"), integer("x2"), integer("y2"), integer("ms", 50, 3000)) }
            "key" -> { keys("key"); string("key").takeIf { it in KEYS }?.let(ScreenRequest::Key) }
            "text" -> { keys("text"); string("text").takeIf(::typeable)?.let(ScreenRequest::Text) }
            "launch" -> { keys("package"); string("package").takeIf(ScreenOffer::validPackage)?.let(ScreenRequest::Launch) }
            "apps" -> { keys(); ScreenRequest.Apps }
            else -> null
        }
    }.getOrNull()

    private fun typeable(text: String) = text.isNotEmpty() && text.codePointCount(0, text.length) <= 256 &&
        HostedPhoneFrames.clean(text, text.length) == text && text.none { it.code < 32 || it.code == 127 }

    /** A request position in pixels of a [size]-pixel axis. */
    fun pixel(value: Int, size: Int): Float = value.toFloat() / SCALE * (size - 1).coerceAtLeast(0)

    fun state(input: Boolean) = buildJsonObject { put("t", "state"); put("input", input) }.toString()
    fun launched(packageName: String, ok: Boolean) = buildJsonObject { put("t", "launched"); put("package", packageName); put("ok", ok) }.toString()

    /** Launchable apps as (package, label): printable labels of 1 to 80 characters, at most 1000 rows. */
    fun appRows(apps: List<Pair<String, String>>): JsonArray = JsonArray(apps.filter { ScreenOffer.validPackage(it.first) }
        .distinctBy { it.first }.take(1000).map { (packageName, label) ->
            val name = HostedPhoneFrames.clean(label.filter { it.code >= 32 && it.code != 127 }.trim(), 80).ifEmpty { packageName.take(80) }
            buildJsonObject { put("package", packageName); put("name", name) }
        })

    fun apps(apps: List<Pair<String, String>>) = buildJsonObject { put("t", "apps"); put("apps", appRows(apps)) }.toString()

    fun frame(jpeg: ByteArray, width: Int, height: Int, sequence: Long): ByteArray {
        require(jpeg.size in 4..(MAX_FRAME - 18) && width in 1..65535 && height in 1..65535)
        return ByteBuffer.allocate(18 + jpeg.size).put(MAGIC).putShort(width.toShort()).putShort(height.toShort())
            .putShort(0).putLong(sequence).put(jpeg).array()
    }

    /**
     * The focused field after typing [typed] (or deleting one character when null) at the
     * selection; returns the new text and cursor. Pairs of UTF-16 units are never split.
     */
    fun edit(current: String, selectionStart: Int, selectionEnd: Int, typed: String?): Pair<String, Int> {
        var start = minOf(selectionStart, selectionEnd); var end = maxOf(selectionStart, selectionEnd)
        if (start < 0 || end > current.length) { start = current.length; end = current.length }
        if (typed != null) return (current.substring(0, start) + typed + current.substring(end)) to (start + typed.length)
        if (start != end) return (current.substring(0, start) + current.substring(end)) to start
        if (start == 0) return current to 0
        val previous = current.offsetByCodePoints(start, -1)
        return (current.substring(0, previous) + current.substring(start)) to previous
    }

    /** Even capture dimensions with the display's aspect, within the offer's longest side and pixel budget. */
    fun captureSize(width: Int, height: Int, maxSide: Int, maxPixels: Int): Pair<Int, Int> {
        require(width > 0 && height > 0)
        val scale = minOf(1.0, maxSide.toDouble() / maxOf(width, height), kotlin.math.sqrt(maxPixels.toDouble() / (width.toDouble() * height)))
        fun even(value: Double) = (value.toInt() and 1.inv()).coerceAtLeast(2)
        return even(width * scale) to even(height * scale)
    }
}
