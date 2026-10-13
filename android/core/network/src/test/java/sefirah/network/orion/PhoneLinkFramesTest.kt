package sefirah.network.orion

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import sefirah.domain.model.*

class PhoneLinkFramesTest {
    private fun info(type: PlaybackInfoType, playing: Boolean = true, title: String? = "Song", position: Double = 0.0) =
        PlaybackInfo(infoType = type, source = "com.spotify.music", trackTitle = title, artist = "Artist", isPlaying = playing,
            position = position, maxSeekTime = 200_000.0, appName = "Spotify", volume = 40, canPlay = true, canPause = true, canGoNext = true)

    @Test fun mediaMergesPartialUpdatesAndIgnoresPositionTicks() {
        val media = OrionMedia()
        val first = media.update(info(PlaybackInfoType.PlaybackInfo))!!
        val session = first.getValue("sessions").jsonArray.single().jsonObject
        assertEquals("Song", session.getValue("title").jsonPrimitive.content)
        assertEquals(false, session.getValue("can_previous").jsonPrimitive.boolean)
        assertNull(media.update(info(PlaybackInfoType.TimelineUpdate, title = null, position = 5_000.0)))
        val paused = media.update(info(PlaybackInfoType.PlaybackUpdate, playing = false, title = null))!!
        assertEquals("Song", paused.getValue("sessions").jsonArray.single().jsonObject.getValue("title").jsonPrimitive.content)
        assertNotNull(media.retain(emptySet()))
        assertEquals(0, media.state().getValue("sessions").jsonArray.size)
    }

    @Test fun contactSearchMatchesNamesAndNumbersAndGroupsNumbers() {
        val all = listOf(ContactInfo("1", "a", "Alice", "+44 7700 900123"), ContactInfo("2", "a", "Alice", "+44 7700 900999"),
            ContactInfo("3", "b", "Bob", "01234 567890"))
        val byName = PhoneFeatureFrames.contacts("ali", all).getValue("contacts").jsonArray.single().jsonObject
        assertEquals(2, byName.getValue("numbers").jsonArray.size)
        val byNumber = PhoneFeatureFrames.contacts("567", all).getValue("contacts").jsonArray
        assertEquals("Bob", byNumber.single().jsonObject.getValue("name").jsonPrimitive.content)
        assertEquals(0, PhoneFeatureFrames.contacts("56", all).getValue("contacts").jsonArray.size) // Too few digits to match numbers.
    }

    @Test fun callHistoryIsNewestFirstAndBounded() {
        val calls = (1..60).map { CallLogInfo(it.toLong(), "+44$it", it * 1000L, 5, if (it % 2 == 0) CallLogType.Missed else CallLogType.Blocked) }
        val rows = PhoneFeatureFrames.callLog(calls).getValue("calls").jsonArray
        assertEquals(50, rows.size)
        assertEquals("+4460", rows.first().jsonObject.getValue("number").jsonPrimitive.content)
        assertEquals(setOf("missed", "rejected"), rows.map { it.jsonObject.getValue("type").jsonPrimitive.content }.toSet())
    }

    @Test fun dialingRefusesMmiCodesAndRingerModesRoundTrip() {
        assertTrue(PhoneFeatureFrames.dialable("+44 (0) 7700-900123"))
        for (code in listOf("*21*07700900123#", "#31#", "tel:123", "()")) assertFalse(code, PhoneFeatureFrames.dialable(code))
        for (mode in listOf("silent", "vibrate", "ring")) assertEquals(mode, PhoneFeatureFrames.ringer(PhoneFeatureFrames.ringerMode(mode)))
        assertNull(PhoneFeatureFrames.ringer(7))
    }

    @Test fun newCapabilitiesFollowPermissions() {
        assertEquals(listOf("files"), FeatureAccess().capabilities())
        val all = FeatureAccess(notifications = true, contacts = true, callLog = true, callDial = true, ringer = true).capabilities()
        assertTrue(all.containsAll(listOf("media", "contacts", "call-log", "call-dial", "ringer")))
        assertFalse(FeatureAccess(contacts = false).allowsPublication("contacts.results"))
        assertFalse(FeatureAccess(callLog = false).allowsPublication("calls.log"))
    }
}
