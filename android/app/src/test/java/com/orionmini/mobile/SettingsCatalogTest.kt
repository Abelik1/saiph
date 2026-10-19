// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import com.orionmini.mobile.SettingsCatalog.Category
import org.junit.Assert.*
import org.junit.Test

class SettingsCatalogTest {
    private fun ids(query: String, entries: List<SettingsCatalog.Entry> = SettingsCatalog.CLOUD) = SettingsCatalog.search(query, entries).map { it.id }

    @Test fun blankQueryFindsNothingSoTheCategoryListShows() {
        assertTrue(ids("").isEmpty())
        assertTrue(ids("   ").isEmpty())
        assertTrue(ids("—").isEmpty())
    }

    @Test fun titleWordsMatchByPrefixAndIgnoreCase() {
        assertEquals("app_lock", ids("APP L").first())
        assertEquals(listOf("photo_gallery"), ids("gall"))
        assertEquals("texts_and_calls", ids("texts").first())
    }

    @Test fun keywordsFindTheSameSettingUnderOtherNames() {
        assertTrue("sign_in" in ids("logout"))
        assertTrue("sign_in" in ids("log out"))
        assertTrue("texts_and_calls" in ids("sms"))
        assertTrue("background" in ids("battery"))
        assertTrue("clipboard" in ids("paste"))
        assertTrue("subscription" in ids("billing"))
    }

    @Test fun everyWordMustMatchSoMoreWordsNarrowTheResults() {
        assertTrue("app_lock" in ids("lock"))
        assertEquals(listOf("app_lock"), ids("lock face"))
        assertTrue(ids("lock giraffe").isEmpty())
    }

    @Test fun matchesAreWordStartsNotArbitrarySubstrings() {
        // "all" is inside "gallery", but no word starts with it.
        assertFalse("photo_gallery" in ids("all"))
    }

    @Test fun titleMatchesRankAboveKeywordAndCategoryMatches() {
        // "Phone notifications" by title; "Saiph alerts" only by keyword; Notifications category by name.
        val found = ids("notifications")
        assertEquals("notification_access", found.first())
        assertTrue(found.indexOf("notification_access") < found.indexOf("saiph_alerts"))
        // Fingerprint is a keyword of both App lock and This phone; catalog order breaks the tie.
        assertEquals(listOf("this_phone", "app_lock"), ids("fingerprint"))
    }

    @Test fun categoryTitlesFindTheirItems() {
        val privacy = ids("security")
        assertTrue(privacy.containsAll(listOf("app_lock", "security_activity", "usage", "policies")))
        assertEquals(ids("Privacy & security"), ids("privacy security"))
    }

    @Test fun accentsAndPunctuationAreIgnored() {
        assertEquals(ids("photo"), ids("phóto"))
        assertEquals(ids("do not disturb", SettingsCatalog.SELF_HOSTED), ids("do-not-disturb", SettingsCatalog.SELF_HOSTED))
        assertEquals("dnd_sync", ids("do-not-disturb", SettingsCatalog.SELF_HOSTED).first())
        assertEquals("ecran", SettingsCatalog.normalise("Écran"))
    }

    @Test fun idsAreUniqueAndEveryItemHasAWayToBeFound() {
        for (catalog in listOf(SettingsCatalog.CLOUD, SettingsCatalog.SELF_HOSTED)) {
            assertEquals(catalog.size, catalog.map { it.id }.toSet().size)
            catalog.forEach { entry -> assertEquals(entry.id, SettingsCatalog.search(entry.title, catalog).first().id) }
        }
    }

    @Test fun categoriesKeepTheirOrderAndHideEmptyOnes() {
        val cloud = SettingsCatalog.categories(SettingsCatalog.CLOUD)
        assertEquals(Category.ACCOUNT, cloud.first())
        assertEquals(Category.ABOUT, cloud.last())
        // The shared phone status switch lives under Status & controls for both connection types.
        assertTrue(Category.STATUS in cloud)
        assertTrue(Category.STATUS in SettingsCatalog.categories(SettingsCatalog.SELF_HOSTED))
        assertEquals(cloud, Category.entries.filter { it in cloud })
        assertFalse(Category.MESSAGES in SettingsCatalog.categories(SettingsCatalog.SELF_HOSTED))
    }

    @Test fun summariesNameWhatTheCategoryHolds() {
        assertEquals("Sync · Background activity", SettingsCatalog.summary(SettingsCatalog.CLOUD, Category.CONNECTION))
        assertEquals("Status and quick controls", SettingsCatalog.summary(SettingsCatalog.CLOUD, Category.STATUS))
    }

    @Test fun everyExistingCloudSettingIsListed() {
        // Settings that existed before categories: none may become unreachable.
        val required = setOf("subscription", "sign_in", "own_hub", "this_phone", "remove_phone", "sync", "background",
            "notification_access", "saiph_alerts", "status_sharing", "app_lock", "security_activity", "usage", "policies")
        assertTrue(SettingsCatalog.CLOUD.map { it.id }.containsAll(required))
        val selfHosted = setOf("saiph_account", "hub_details", "saiph_on", "tailscale", "permissions", "dnd_sync", "sleep_plan",
            "clipboard", "backups", "status_sharing", "app_lock", "usage", "updates")
        assertEquals(selfHosted, SettingsCatalog.SELF_HOSTED.map { it.id }.toSet())
    }
}
