// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.content.Context
import android.view.View
import java.net.URI

/**
 * Debug builds only: point the updater at a local test server, for example the synthetic
 * manifest in docs/ANDROID_UPDATES.md served on a laptop. This file is in the debug source set;
 * beta and release builds compile a stub that returns nothing, so they cannot be redirected.
 *
 * The server must offer `release.json` (the Saiph account schema, checked as strictly as the
 * real one) and `saiph.apk` under the saved base address. Hash, size, version and signer
 * checks are unchanged.
 */
object UpdateDebugOverride {
    private const val PREFS = "orion_updates_debug"

    private fun base(context: Context): String? =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString("base", null)?.takeIf { valid(it) }

    internal fun valid(value: String): Boolean = runCatching {
        val uri = URI(value)
        uri.scheme in listOf("http", "https") && !uri.host.isNullOrBlank() && uri.rawUserInfo == null &&
            uri.rawQuery == null && uri.rawFragment == null && uri.rawPath.endsWith("/") && value.length <= 512
    }.getOrDefault(false)

    fun source(context: Context): UpdateSource? = base(context)?.let { base ->
        object : UpdateSource {
            override val place = "the debug test server"
            override suspend fun latest(): AppRelease? {
                val request = okhttp3.Request.Builder().url(base + "release.json").header("Accept", "application/json").build()
                UpdateHttp.client.newCall(request).execute().use { response ->
                    return when (response.code) {
                        200 -> UpdateManifest.hosted(UpdateHttp.small(response.body))
                        204, 404 -> null
                        else -> throw java.io.IOException("Debug source failed (HTTP ${response.code})")
                    }
                }
            }
            override suspend fun opener() = ResumableDownload.Opener { offset -> UpdateHttp.apk(base + "saiph.apk", offset) }
        }
    }

    /** A field under Settings > Version and updates, debug builds only. */
    fun controls(context: Context): List<View> = with(context) {
        val prefs = getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val note = text(base(this)?.let { "Debug: updates come from $it" } ?: "Debug: updates use the normal source.", UiType.META, Palette.WARN)
        val input = field("Debug update server, e.g. http://192.168.1.20:8000/").apply { setText(prefs.getString("base", "")) }
        val save = compactButton("Use debug server") {
            val value = input.text.toString().trim()
            if (value.isEmpty()) { prefs.edit().remove("base").apply(); note.text = "Debug: updates use the normal source." }
            else if (valid(value)) { prefs.edit().putString("base", value).apply(); note.text = "Debug: updates come from $value" }
            else note.text = "Debug: use http(s)://host:port/ ending in /"
        }
        listOf(note, input, compactActions(save))
    }
}
