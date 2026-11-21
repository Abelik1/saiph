// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.os.Build
import com.castle.sefirah.BuildConfig
import org.junit.Assert.*
import org.junit.Test
import sefirah.common.util.locationAccessSufficient
import java.io.File

/**
 * Google Play policy pieces that both builds share (docs/ANDROID_DISTRIBUTION.md): the in-app
 * path to delete a Saiph account, and trusted Wi-Fi detection without background location in
 * the Play build. Runs for both flavors (testDirectDebugUnitTest, testPlayDebugUnitTest).
 */
class PlayPolicyTest {
    private val q = Build.VERSION_CODES.Q

    @Test fun accountDeletionOpensTheAccountSitesDeletionPage() {
        assertEquals("https://account.example.test/account/delete", AppPolicy.deletionUrl("https://account.example.test"))
        assertEquals("https://account.example.test/account/delete", AppPolicy.deletionUrl("https://Account.Example.Test"))
        for (bad in listOf("", "http://account.example.test", "https://account.example.test/", "https://account.example.test/x",
                "https://account.example.test:8443", "https://user@account.example.test", "https://account.example.test?x=1",
                "https://account.example.test#x", "account.example.test", "javascript:alert(1)")) {
            assertNull(bad, AppPolicy.deletionUrl(bad))
        }
        // The build's own origin, when it has one, gives a deletion page (empty for independent builds).
        val origin = BuildConfig.ACCOUNT_ORIGIN
        assertEquals(origin.isNotEmpty(), AppPolicy.deletionUrl(origin) != null)
    }

    @Test fun deleteAccountIsInBothBuildsUnderAccountAndFoundByWhatPeopleCallIt() {
        for (play in listOf(true, false)) {
            val entries = SettingsCatalog.forBuild(SettingsCatalog.CLOUD, playStore = play)
            val entry = entries.single { it.id == "delete_account" }
            assertEquals(SettingsCatalog.Category.ACCOUNT, entry.category)
            for (query in listOf("delete account", "Delete my account", "erase", "close account", "gdpr"))
                assertEquals(query, "delete_account", SettingsCatalog.search(query, entries).first().id)
            assertTrue("delete_account" in SettingsCatalog.search("delete", entries).map { it.id })
        }
        // Drawn for every Cloud phone, enrolled or not, and not behind the Play switch.
        val activity = File("src/main/java/com/orionmini/mobile/HostedActivity.kt").readText()
        val drawn = activity.substringAfter("SettingsCatalog.Category.ACCOUNT -> {").substringBefore("SettingsCatalog.Category.CONNECTION ->")
        assertTrue(drawn.contains("page.linkItem(\"delete_account\"") && drawn.contains("page.item(\"delete_account\""))
        assertTrue(drawn.contains("AppPolicy.deletionUrl(com.castle.sefirah.BuildConfig.ACCOUNT_ORIGIN)"))
        val line = drawn.lines().first { "delete_account" in it }
        assertFalse(line.contains("PLAY_STORE"))
    }

    @Test fun trustedNetworksNeedBackgroundLocationOnlyWhereTheBuildAsksForIt() {
        // Direct build: unchanged, fine plus background location on Android 10 and later.
        assertTrue(locationAccessSufficient(fine = true, background = true, sdk = 34, backgroundLocation = true))
        assertFalse(locationAccessSufficient(fine = true, background = false, sdk = 34, backgroundLocation = true))
        assertTrue(locationAccessSufficient(fine = true, background = false, sdk = q - 1, backgroundLocation = true))
        // Play build: foreground location is enough on every Android version.
        assertTrue(locationAccessSufficient(fine = true, background = false, sdk = q, backgroundLocation = false))
        assertTrue(locationAccessSufficient(fine = true, background = false, sdk = 35, backgroundLocation = false))
        for (asks in listOf(true, false)) assertFalse(locationAccessSufficient(fine = false, background = true, sdk = 34, backgroundLocation = asks))
    }

    @Test fun thePlayBuildNeverAsksForBackgroundLocation() {
        val play = File("src/play/AndroidManifest.xml").readText()
        assertTrue(Regex("""ACCESS_BACKGROUND_LOCATION"\s+tools:node="remove"""").containsMatchIn(play))
        // The policy comes from BuildConfig.PLAY_STORE before anything checks location...
        val application = File("src/main/java/com/castle/sefirah/MainApplication.kt").readText()
        assertTrue(application.contains("LocationPolicy.backgroundLocation = !BuildConfig.PLAY_STORE"))
        assertTrue(application.indexOf("LocationPolicy.backgroundLocation") < application.indexOf("super.onCreate()"))
        // ...and every request for background location is behind the same flag.
        File("src/main/java").walkTopDown().filter { it.extension == "kt" }.forEach { file ->
            file.readLines().forEachIndexed { index, line ->
                if ("launch(Manifest.permission.ACCESS_BACKGROUND_LOCATION)" in line) {
                    val guard = file.readLines().subList(maxOf(0, index - 3), index).joinToString("\n")
                    assertTrue("${file.name}:${index + 1} asks without the Play guard", guard.contains("!BuildConfig.PLAY_STORE") ||
                        guard.contains("!com.castle.sefirah.BuildConfig.PLAY_STORE"))
                }
            }
        }
    }
}
