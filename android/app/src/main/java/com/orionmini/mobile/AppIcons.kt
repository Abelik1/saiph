// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.drawable.Drawable
import android.os.Build
import kotlinx.serialization.json.*
import sefirah.network.orion.HostedPhoneFrames
import java.io.ByteArrayOutputStream
import java.util.Base64

/**
 * App icons for the computer's Apps grid (docs/PHONE_SCREEN.md), over the sealed
 * Saiph Cloud events `apps.icons.request` and `apps.icons`; the desktop half is in
 * `hosted_features.py` and `phone_app_library.py`.
 *
 * Only apps with a launcher icon (the same list the computer already receives) are
 * answered, each as one small static WebP of at most 12,000 bytes and 96 pixels, with
 * the app's version so the computer caches it until the app updates. An app whose
 * icon the computer already has at this version, or that is not listed, goes in
 * `same`: nothing new. The runtime sends answers only to the requesting computer,
 * only while the owner lets computers list apps.
 */
internal object AppIcons {
    const val REQUEST = "apps.icons.request"
    const val ANSWER = "apps.icons"
    const val MAX_ROWS = 24
    const val MAX_BYTES = 12_000
    private const val MAX_SAFE = 9_007_199_254_740_991L
    /** Sizes and WebP qualities tried in turn until an icon fits [MAX_BYTES]. */
    val ATTEMPTS = listOf(96 to 85, 96 to 70, 80 to 60, 64 to 50)
    private const val REQUESTS_PER_MINUTE = 12

    data class Want(val packageName: String, val known: Long)
    /** [data] null: nothing new for this app (unchanged, unlisted or not encodable). */
    class Icon(val packageName: String, val version: Long, val data: ByteArray?)

    /** The exact request shape, or null. */
    fun request(payload: JsonObject): List<Want>? = runCatching {
        require(payload.keys == setOf("type", "apps") && payload["type"] == JsonPrimitive(REQUEST))
        val rows = payload.getValue("apps").jsonArray
        require(rows.size in 1..MAX_ROWS)
        rows.map { row ->
            val value = row.jsonObject
            require(value.keys == setOf("package", "version"))
            val name = value.getValue("package").jsonPrimitive.also { require(it.isString) }.content
            val version = value.getValue("version").jsonPrimitive.also { require(!it.isString && Regex("0|[1-9][0-9]{0,15}").matches(it.content)) }.content.toLong()
            require(ScreenOffer.validPackage(name) && version in 0..MAX_SAFE)
            Want(name, version)
        }.also { wants -> require(wants.distinctBy { it.packageName }.size == wants.size) }
    }.getOrNull()

    /** The first encoding that fits, trying smaller and lower-quality images; null when none does. */
    fun bounded(encode: (side: Int, quality: Int) -> ByteArray?): ByteArray? =
        ATTEMPTS.firstNotNullOfOrNull { (side, quality) -> runCatching { encode(side, quality) }.getOrNull()?.takeIf { it.size in 26..MAX_BYTES } }

    /** What to send for one wanted app given its current version and a lazy encoder. */
    fun decide(want: Want, listed: Boolean, version: Long?, encode: () -> ByteArray?): Icon =
        if (!listed || version == null) Icon(want.packageName, 0, null)
        else if (want.known != 0L && want.known == version) Icon(want.packageName, version, null)
        else Icon(want.packageName, version, encode())

    /** Answer events, each fitting one sealed event; every `same` package goes in the first. */
    fun answers(icons: List<Icon>): List<JsonObject> {
        fun event(rows: List<Icon>, same: List<String>) = buildJsonObject {
            put("type", ANSWER)
            put("icons", JsonArray(rows.map { icon -> buildJsonObject {
                put("package", icon.packageName); put("version", icon.version)
                put("data", Base64.getEncoder().encodeToString(icon.data))
            } }))
            put("same", JsonArray(same.map(::JsonPrimitive)))
        }
        val same = icons.filter { it.data == null }.map { it.packageName }.distinct()
        val sending = icons.filter { it.data != null }.distinctBy { it.packageName }
        val events = mutableListOf<Pair<MutableList<Icon>, List<String>>>(mutableListOf<Icon>() to same)
        for (icon in sending) {
            val (rows, unchanged) = events.last()
            if (rows.size + unchanged.size < MAX_ROWS && HostedPhoneFrames.fits(event(rows + icon, unchanged))) rows += icon
            else if (HostedPhoneFrames.fits(event(listOf(icon), emptyList()))) events += mutableListOf(icon) to emptyList()
        }
        return events.filter { (rows, unchanged) -> rows.isNotEmpty() || unchanged.isNotEmpty() }.map { (rows, unchanged) -> event(rows, unchanged) }
    }

    private val asked = HashMap<String, MutableList<Long>>()
    /** At most a dozen icon requests a minute per computer. */
    @Synchronized fun allow(source: String, now: Long = System.currentTimeMillis()): Boolean {
        val times = asked.getOrPut(source) { mutableListOf() }
        times.removeAll { it <= now - 60_000 }
        if (times.size >= REQUESTS_PER_MINUTE) return false
        times += now
        if (asked.size > 64) asked.keys.retainAll(setOf(source))
        return true
    }

    @Suppress("DEPRECATION")
    fun version(context: Context, packageName: String): Long? = runCatching {
        val info = context.packageManager.getPackageInfo(packageName, 0)
        (if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) info.longVersionCode else info.versionCode.toLong()).coerceIn(0, MAX_SAFE)
    }.getOrNull()

    /** One launcher icon as a small static WebP, or null. */
    @Suppress("DEPRECATION")
    fun encode(drawable: Drawable): ByteArray? = bounded { side, quality ->
        val bitmap = Bitmap.createBitmap(side, side, Bitmap.Config.ARGB_8888)
        try {
            val canvas = Canvas(bitmap)
            drawable.setBounds(0, 0, side, side)
            drawable.draw(canvas)
            val format = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) Bitmap.CompressFormat.WEBP_LOSSY else Bitmap.CompressFormat.WEBP
            ByteArrayOutputStream(8192).also { bitmap.compress(format, quality, it) }.toByteArray()
        } finally { bitmap.recycle() }
    }

    /** The answer events for one request, from this phone's launcher apps only. */
    fun answer(context: Context, wants: List<Want>): List<JsonObject> {
        val listed = PhoneApps.list(context).map { it.first }.toSet()
        val manager = context.packageManager
        return answers(wants.map { want ->
            decide(want, want.packageName in listed, version(context, want.packageName)) {
                runCatching { encode(manager.getApplicationIcon(want.packageName)) }.getOrNull()
            }
        })
    }
}
