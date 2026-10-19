// SPDX-License-Identifier: GPL-3.0-only
package sefirah.network.orion

import org.junit.Assert.*
import org.junit.Test

class FindPhoneRingTest {
    private val ring = FindPhoneRing(30_000)

    @Test fun startRingsForTheFullTimeAndNamesTheComputer() {
        val state = ring.start("  Studio PC ", 1_000)
        assertEquals(FindPhoneRing.State.Ringing("Studio PC", 31_000), state)
        assertEquals(state, ring.state)
        assertEquals(30, ring.remaining(1_000))
        assertEquals(1, ring.remaining(30_500))
    }

    @Test fun anUnknownOrBlankComputerIsLeftUnnamedAndLongNamesAreBounded() {
        assertNull(ring.start(null, 0).from)
        assertNull(ring.start("   ", 0).from)
        assertEquals(80, ring.start("x".repeat(200), 0).from!!.length)
    }

    @Test fun stopEndsTheRingOnceFromAnyPlace() {
        ring.start("PC", 0)
        assertTrue(ring.stop())
        assertEquals(FindPhoneRing.State.Idle, ring.state)
        assertFalse(ring.stop()) // A second Stop (notification after screen) does nothing more.
        assertEquals(0, ring.remaining(0))
    }

    @Test fun ringingIsAlwaysTimeBounded() {
        ring.start("PC", 0)
        assertFalse(ring.expire(29_999))
        assertTrue(ring.state is FindPhoneRing.State.Ringing)
        assertTrue(ring.expire(30_000))
        assertEquals(FindPhoneRing.State.Idle, ring.state)
        assertFalse(ring.expire(40_000))
    }

    @Test fun aNewRequestRestartsTheTimeAndTheEarlierTimerCannotEndIt() {
        ring.start("Laptop", 0)
        ring.start("Desktop", 20_000)
        assertFalse(ring.expire(30_000)) // The first request's timer fires; the second keeps ringing.
        assertEquals("Desktop", (ring.state as FindPhoneRing.State.Ringing).from)
        assertTrue(ring.expire(50_000))
    }

    @Test fun dismissingTheNotificationDoesNotStopTheRing() {
        ring.start("PC", 0)
        assertTrue(ring.dismissed(10_000)) // Post it again: Stop stays one tap away.
        assertTrue(ring.state is FindPhoneRing.State.Ringing)
    }

    @Test fun dismissingAfterTheTimeIsUpEndsItInsteadOfReposting() {
        ring.start("PC", 0)
        assertFalse(ring.dismissed(30_000))
        assertEquals(FindPhoneRing.State.Idle, ring.state)
        assertFalse(FindPhoneRing(30_000).dismissed(0)) // Nothing to bring back when idle.
    }
}
