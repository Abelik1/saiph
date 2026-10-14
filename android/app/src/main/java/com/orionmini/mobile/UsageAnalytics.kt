// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.app.AlertDialog
import android.content.Context
import android.view.View
import android.widget.Switch
import android.widget.TextView
import androidx.activity.ComponentActivity
import com.castle.sefirah.BuildConfig
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.CookieJar
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.time.LocalDate
import java.time.ZoneOffset
import java.time.temporal.ChronoUnit
import java.util.concurrent.TimeUnit

/**
 * Opt-in, anonymous daily usage counts. The public field list is docs/USAGE_ANALYTICS.md.
 *
 * Nothing is counted or sent until the owner agrees; declining deletes the local
 * counts. A batch carries no install, account or device identifier and no names,
 * numbers, app names, file names or content: only which features were used, in
 * coarse ranges, plus app version and setup progress. Builds without a packaged
 * Saiph service never send.
 */
object UsageAnalytics {
    val FEATURES = setOf(
        "app_open", "clipboard_sent", "clipboard_received", "notification_shared", "hosted_file_send",
        "hosted_file_save", "pairing_started", "hosted_enrolled", "dnd_shared",
        "screen_home", "screen_settings", "screen_advanced", "screen_hosted",
    )
    /** Link event types counted when this phone publishes them (type only, never the payload). */
    private val EVENTS = mapOf("clipboard" to "clipboard_sent", "notification.upsert" to "notification_shared", "focus.state" to "dnd_shared")
    private const val KEEP_DAYS = 7L
    private const val RETRY_MS = 6 * 3600_000L
    private val VERSION = Regex("[0-9]{1,4}\\.[0-9]{1,4}\\.[0-9]{1,4}(?:[-+.][A-Za-z0-9.]{1,20})?")
    private var askedThisProcess = false

    private fun prefs(context: Context) = context.getSharedPreferences("orion_usage", Context.MODE_PRIVATE)
    private fun today() = LocalDate.now(ZoneOffset.UTC)

    fun endpoint(context: Context): String? = runCatching {
        val raw = context.assets.open("hosted-defaults.json").use { it.readBytes() }
        check(raw.size <= 4096)
        val origin = JSONObject(raw.toString(Charsets.UTF_8)).getString("service_url")
        val uri = java.net.URI(origin)
        check(uri.scheme == "https" && !uri.host.isNullOrBlank() && uri.rawUserInfo == null && uri.rawPath.isNullOrEmpty() && uri.rawQuery == null && uri.rawFragment == null)
        "$origin/v1/usage"
    }.getOrNull()

    fun available(context: Context) = endpoint(context) != null
    fun consent(context: Context): String? = prefs(context).getString("consent", null)?.takeIf { it == "granted" || it == "declined" }

    @Synchronized fun setConsent(context: Context, granted: Boolean) {
        val editor = prefs(context).edit().putString("consent", if (granted) "granted" else "declined")
        if (granted) { if (!prefs(context).contains("first_day")) editor.putString("first_day", today().toString()) }
        else {
            // Declining removes everything counted so far, including the last batch shown.
            prefs(context).all.keys.filter { it.startsWith("d:") }.forEach { editor.remove(it) }
            editor.remove("last_sent").remove("first_day")
        }
        editor.commit()
    }

    @Synchronized fun count(context: Context, feature: String) {
        if (feature !in FEATURES || consent(context) != "granted") return
        val key = "d:${today()}:$feature"
        prefs(context).edit().putInt(key, (prefs(context).getInt(key, 0) + 1).coerceAtMost(1_000_000)).apply()
    }
    fun event(context: Context, type: String) { EVENTS[type]?.let { count(context, it) } }

    private fun bucket(count: Int) = when { count <= 1 -> "1"; count <= 5 -> "2-5"; count <= 20 -> "6-20"; else -> "21+" }
    private fun age(days: Long) = when { days <= 0 -> "0"; days < 7 -> "1-6"; days < 30 -> "7-29"; days < 90 -> "30-89"; else -> "90+" }
    private fun mode(context: Context) = when {
        context.getSharedPreferences("orion", Context.MODE_PRIVATE).contains("device_id") -> "hub"
        context.getSharedPreferences("orion_hosted", Context.MODE_PRIVATE).contains("device_id") -> "hosted"
        else -> "none"
    }

    /** Exactly the batches that would be sent: completed past days only. */
    @Synchronized fun pending(context: Context): List<JSONObject> {
        val today = today()
        val first = prefs(context).getString("first_day", null)?.let { runCatching { LocalDate.parse(it) }.getOrNull() } ?: today
        val version = BuildConfig.VERSION_NAME.takeIf { VERSION.matches(it) } ?: "0.0.0"
        val counts = sortedMapOf<String, MutableMap<String, Int>>()
        for ((key, value) in prefs(context).all) {
            val parts = key.split(':')
            if (parts.size != 3 || parts[0] != "d" || parts[2] !in FEATURES || value !is Int || value < 1) continue
            counts.getOrPut(parts[1]) { sortedMapOf() }[parts[2]] = value
        }
        val stage = if (mode(context) == "none") "installed" else "connected"
        return counts.mapNotNull { (day, features) ->
            val date = runCatching { LocalDate.parse(day) }.getOrNull() ?: return@mapNotNull null
            if (!date.isBefore(today) || ChronoUnit.DAYS.between(date, today) > KEEP_DAYS) return@mapNotNull null
            JSONObject().put("schema", 1).put("day", day).put("app", "android").put("platform", "android")
                .put("version", version).put("mode", mode(context))
                .put("install_age", age(ChronoUnit.DAYS.between(first, date).coerceAtLeast(0)))
                .put("stage", stage).put("features", JSONObject(features.mapValues { bucket(it.value) }))
        }
    }

    /** Send due batches on a background thread; failures keep them for later. */
    fun flush(context: Context) {
        val endpoint = endpoint(context) ?: return
        if (consent(context) != "granted") return
        val now = System.currentTimeMillis()
        synchronized(this) {
            if (now - prefs(context).getLong("last_attempt", 0) < RETRY_MS) return
            prefs(context).edit().putLong("last_attempt", now).apply()
            // Days the service no longer accepts are dropped unsent.
            val editor = prefs(context).edit()
            prefs(context).all.keys.filter { key -> key.startsWith("d:") && runCatching {
                ChronoUnit.DAYS.between(LocalDate.parse(key.split(':')[1]), today()) > KEEP_DAYS }.getOrDefault(true) }.forEach { editor.remove(it) }
            editor.commit()
        }
        val client = OkHttpClient.Builder().followRedirects(false).followSslRedirects(false).cookieJar(CookieJar.NO_COOKIES)
            .callTimeout(15, TimeUnit.SECONDS).build()
        try {
            for (batch in pending(context)) {
                val request = Request.Builder().url(endpoint).post(batch.toString().toRequestBody("application/json".toMediaType())).build()
                val accepted = runCatching { client.newCall(request).execute().use { it.code in listOf(200, 202, 204) } }.getOrDefault(false)
                if (!accepted) break
                synchronized(this) {
                    val day = batch.getString("day")
                    val editor = prefs(context).edit()
                    prefs(context).all.keys.filter { it.startsWith("d:$day:") }.forEach { editor.remove(it) }
                    editor.putString("last_sent", batch.toString()).commit()
                }
            }
        } finally { client.dispatcher.executorService.shutdown() }
    }

    private const val EXPLANATION = "Saiph can send anonymous counts of which features you use, once a day, so we know what to improve. It's off unless you agree.\n\n" +
        "Sent: which features and screens were used that day, in rough ranges (like \"2–5 times\"), the app version and how far setup got.\n\n" +
        "Never sent: your messages, notifications, clipboard, files, contacts, phone numbers, names, app names or anything you type. No account or device ID is attached.\n\n" +
        "You can see every batch before it's sent and change your mind any time in Settings. Turning it off deletes the counts on this phone."

    /** One-time question; "Ask later" asks again next time Saiph opens. */
    fun ask(activity: ComponentActivity, onDone: () -> Unit = {}) {
        if (!available(activity) || consent(activity) != null || askedThisProcess) return
        askedThisProcess = true
        AlertDialog.Builder(activity).setTitle("Help improve Saiph?").setMessage(EXPLANATION)
            .setPositiveButton("Share anonymous usage") { _, _ -> setConsent(activity, true); onDone() }
            .setNegativeButton("Don't share") { _, _ -> setConsent(activity, false); onDone() }
            .setNeutralButton("Ask later", null).show()
    }

    /** Settings controls: the choice, and exactly what would be or was sent. */
    fun settingsViews(activity: ComponentActivity): List<View> {
        if (!available(activity)) return emptyList()
        val status = activity.text(if (consent(activity) == "granted") "Anonymous daily counts are shared." else "Nothing is counted or sent.", 13f, Palette.MUTED)
        val toggle = Switch(activity).saiph().apply {
            text = "Share anonymous usage statistics"; setTextColor(Palette.TEXT); isChecked = consent(activity) == "granted"
            setOnCheckedChangeListener { _, checked ->
                setConsent(activity, checked)
                status.text = if (checked) "Anonymous daily counts are shared." else "Nothing is counted or sent. Local counts were deleted."
            }
        }
        val show = activity.button("See what Saiph sends") {
            val waiting = pending(activity).joinToString("\n\n") { it.toString(2) }.ifEmpty { "Nothing is waiting. Today's counts are sent after the day ends." }
            val last = prefs(activity).getString("last_sent", null)?.let { runCatching { JSONObject(it).toString(2) }.getOrNull() }
            val body = TextView(activity).apply {
                setTextIsSelectable(true); textSize = 12f; setPadding(activity.dp(20), activity.dp(12), activity.dp(20), 0)
                text = if (consent(activity) != "granted") EXPLANATION else "Waiting to be sent:\n$waiting" + (last?.let { "\n\nLast sent:\n$it" } ?: "")
            }
            AlertDialog.Builder(activity).setTitle("What Saiph sends").setView(android.widget.ScrollView(activity).apply { addView(body) })
                .setPositiveButton("Close", null).show()
        }
        return listOf(activity.section("Usage statistics"), toggle, status, show)
    }

    /** Called when an activity opens: count it and send anything due, off the main thread. */
    fun opened(activity: ComponentActivity, screen: String) {
        count(activity, "screen_$screen")
        activity.lifecycleScope.launch { withContext(Dispatchers.IO) { runCatching { flush(activity.applicationContext) } } }
    }
}
