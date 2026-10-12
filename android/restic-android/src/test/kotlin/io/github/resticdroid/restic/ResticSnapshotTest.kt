package io.github.resticdroid.restic

import org.junit.Assert.assertEquals
import org.junit.Test

class ResticSnapshotTest {

    private fun at(time: String) = ResticSnapshot(
        id = time, shortId = time.take(8), time = time,
        hostname = "h", username = "u", paths = emptyList(), tags = emptyList(), summary = null,
    )

    @Test
    fun `snapshots order by the moment, not by the text of the timestamp`() {
        // The phone stamps UTC because Go pins the local zone there; the
        // desktop stamps +03:00. As text the desktop's sorts later, and it is
        // an hour older.
        val phone = at("2026-09-06T10:00:00Z")
        val desktop = at("2026-09-06T12:00:00+03:00")

        assertEquals(
            listOf(phone, desktop),
            listOf(desktop, phone).sortedByDescending { it.instant },
        )
    }

    @Test
    fun `a timestamp that will not parse sinks to the bottom`() {
        val good = at("2026-09-06T10:00:00Z")
        val bad = at("who knows")

        assertEquals(
            listOf(good, bad),
            listOf(bad, good).sortedByDescending { it.instant },
        )
    }
}
