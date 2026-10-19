// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import org.junit.Assert.*
import org.junit.Test

class CameraCadenceTest {
    @Test fun twentyOnThirtyFpsSensorDoesNotBecomeFifteen() {
        val cadence = CameraCadence(20)
        val accepted = (0 until 90).count { cadence.take(it * 1_000_000_000L / 30) }
        assertEquals(60, accepted)
    }
    @Test fun longPauseDoesNotScheduleAnUnboundedCatchupBurst() {
        val cadence = CameraCadence(20)
        assertTrue(cadence.take(0)); assertFalse(cadence.take(1))
        assertTrue(cadence.take(10_000_000_000))
        assertTrue(cadence.take(10_000_000_001))
        assertFalse(cadence.take(10_000_000_002))
    }
}
