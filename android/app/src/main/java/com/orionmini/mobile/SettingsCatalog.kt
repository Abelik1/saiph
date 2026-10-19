// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import java.text.Normalizer
import java.util.Locale

/**
 * Settings are a short list of category pages and a search that jumps straight to one item.
 * This is the plain model, so search can be tested without Android: the categories in their
 * fixed order, the items each connection type offers, and the words people look for them by.
 * Pages are drawn by [settingsPage] and friends in SettingsPages.kt; each drawn item uses the
 * same [Entry.id], so a search result always lands on a real row.
 *
 * Adding a setting: add an [Entry] to [CLOUD] or [SELF_HOSTED] under the category it belongs
 * to (see docs/MOBILE_DESIGN_SYSTEM.md, "Settings"), then draw it with `item(id)` on that page.
 */
object SettingsCatalog {
    /** Top-level order is fixed; a category without items for this connection type is hidden. */
    enum class Category(val title: String) {
        ACCOUNT("Account & devices"),
        CONNECTION("Connection"),
        NOTIFICATIONS("Notifications"),
        MESSAGES("Messages & calls"),
        PHOTOS("Photos & files"),
        CLIPBOARD("Clipboard"),
        CAMERA("Camera & screen"),
        STATUS("Status & controls"),
        PRIVACY("Privacy & security"),
        ABOUT("About & help"),
    }

    /** One setting a person can look for. [keywords] are other words for the same thing. */
    data class Entry(val id: String, val category: Category, val title: String, val keywords: List<String> = emptyList())

    private fun entry(id: String, category: Category, title: String, vararg keywords: String) = Entry(id, category, title, keywords.toList())

    /** Saiph account (Cloud) phones: HostedActivity. */
    val CLOUD: List<Entry> = listOf(
        entry("subscription", Category.ACCOUNT, "Subscription", "plan", "billing", "payment", "subscribe", "manage subscription"),
        entry("sign_in", Category.ACCOUNT, "Sign in and out", "sign out", "log out", "logout", "sign in", "google", "account"),
        entry("own_hub", Category.ACCOUNT, "Your own Hub", "self-hosted", "self host", "hub", "server", "switch"),
        entry("this_phone", Category.ACCOUNT, "This phone", "fingerprint", "security code", "device", "approval", "request code", "fresh request"),
        entry("remove_phone", Category.ACCOUNT, "Remove this phone", "retire", "delete", "unpair", "forget", "remove"),
        entry("sync", Category.CONNECTION, "Sync", "pause", "turn off", "resume", "on", "off", "connection", "cloud"),
        entry("background", Category.CONNECTION, "Background activity", "battery", "optimisation", "optimization", "restrictions", "doze"),
        entry("notification_access", Category.NOTIFICATIONS, "Phone notifications", "notification access", "listener", "mirror", "share notifications"),
        entry("saiph_alerts", Category.NOTIFICATIONS, "Saiph alerts", "status alerts", "connection notifications", "app notifications"),
        entry("texts_and_calls", Category.MESSAGES, "Texts and calls", "sms", "messages", "text", "calls", "phone", "dial", "answer", "contacts"),
        entry("photo_gallery", Category.PHOTOS, "Photo gallery", "photos", "pictures", "images", "gallery", "media", "photo access"),
        entry("clipboard", Category.CLIPBOARD, "Clipboard sharing", "copy", "paste", "clipboard"),
        entry("webcam", Category.CAMERA, "Phone as webcam", "camera", "webcam", "video"),
        entry("camera_access", Category.CAMERA, "Camera access", "camera permission", "android camera"),
        entry("status_sharing", Category.STATUS, "Status and quick controls", "battery", "wifi", "bluetooth", "signal", "ring", "find my phone", "sound mode", "do not disturb", "media", "quick actions"),
        entry("app_lock", Category.PRIVACY, "App lock", "fingerprint", "face", "pin", "biometric", "lock", "unlock"),
        entry("security_activity", Category.PRIVACY, "Security activity", "events", "log", "history", "security"),
        entry("usage", Category.PRIVACY, "Usage statistics", "analytics", "anonymous", "telemetry", "statistics"),
        entry("policies", Category.PRIVACY, "Privacy policy and terms", "privacy", "terms", "legal", "policy"),
        entry("updates", Category.ABOUT, "Version and updates", "update", "version", "upgrade", "about", "build", "release"),
    )

    /** Self-hosted Hub phones: OrionActivity. */
    val SELF_HOSTED: List<Entry> = listOf(
        entry("saiph_account", Category.ACCOUNT, "Saiph account", "cloud", "account", "sign in", "subscription"),
        entry("hub_details", Category.ACCOUNT, "Hub and device", "hub", "server", "device id", "address"),
        entry("saiph_on", Category.CONNECTION, "Saiph is on", "pause", "resume", "turn off", "on", "off", "widget"),
        entry("tailscale", Category.CONNECTION, "Tailscale and VPN", "vpn", "mesh", "always-on", "tailscale"),
        entry("permissions", Category.CONNECTION, "Permissions and background", "battery", "permissions", "setup", "automatic", "background"),
        entry("dnd_sync", Category.NOTIFICATIONS, "Do Not Disturb sync", "dnd", "do not disturb", "focus", "silence"),
        entry("sleep_plan", Category.NOTIFICATIONS, "Shared sleep plan", "sleep", "bedtime", "focus", "plan"),
        entry("clipboard", Category.CLIPBOARD, "Clipboard sharing", "copy", "paste", "clipboard"),
        entry("backups", Category.PHOTOS, "Backups", "backup", "restic", "files", "photos", "restore"),
        entry("status_sharing", Category.STATUS, "Status and quick controls", "battery", "wifi", "bluetooth", "signal", "ring", "find my phone", "sound mode", "do not disturb", "media", "quick actions"),
        entry("app_lock", Category.PRIVACY, "App lock", "fingerprint", "face", "pin", "biometric", "lock", "unlock"),
        entry("usage", Category.PRIVACY, "Usage statistics", "analytics", "anonymous", "telemetry", "statistics"),
        entry("updates", Category.ABOUT, "Version and updates", "update", "version", "upgrade", "about", "release"),
    )

    /** Categories with at least one item, in their fixed order. */
    fun categories(entries: List<Entry>): List<Category> = Category.entries.filter { category -> entries.any { it.category == category } }

    fun inCategory(entries: List<Entry>, category: Category): List<Entry> = entries.filter { it.category == category }

    /** A category's one-line summary: the names of what it holds, so it never drifts from the page. */
    fun summary(entries: List<Entry>, category: Category): String = inCategory(entries, category).joinToString(" · ") { it.title }

    /** Lower case, without accents or punctuation, so "Écran" finds "ecran" and "do-not-disturb" finds "do not disturb". */
    fun normalise(value: String): String = Normalizer.normalize(value, Normalizer.Form.NFD)
        .replace(Regex("\\p{M}+"), "").lowercase(Locale.ROOT).replace(Regex("[^\\p{L}\\p{N}]+"), " ").trim()

    /**
     * Every word typed must start a word in the item's title, its keywords or its category's
     * title. Title matches come first, then keyword matches, then category matches; ties keep
     * the catalog's order. A blank query finds nothing, so the category list shows instead.
     */
    fun search(query: String, entries: List<Entry>): List<Entry> {
        val words = normalise(query).split(' ').filter { it.isNotEmpty() }
        if (words.isEmpty()) return emptyList()
        fun starts(text: String) = normalise(text).split(' ').let { parts -> words.all { word -> parts.any { it.startsWith(word) } } }
        return entries.mapIndexedNotNull { index, entry ->
            val rank = when {
                starts(entry.title) -> 0
                starts((listOf(entry.title) + entry.keywords).joinToString(" ")) -> 1
                starts((listOf(entry.title, entry.category.title) + entry.keywords).joinToString(" ")) -> 2
                else -> return@mapIndexedNotNull null
            }
            Triple(rank, index, entry)
        }.sortedWith(compareBy({ it.first }, { it.second })).map { it.third }
    }
}
