package com.orionmini.mobile

import org.junit.Assert.*
import org.junit.Test

class PushRegistrationGateTest {
    @Test fun refreshesCannotOverlapOrFloodAnUnavailableHub() {
        val gate = PushRegistrationGate(300_000)
        assertTrue(gate.begin(100))
        assertFalse(gate.begin(300_101)) // Still in flight even after the retry deadline.
        gate.finished(false)
        assertFalse(gate.begin(300_099))
        assertTrue(gate.begin(300_100))
        gate.finished(true)
        assertFalse(gate.begin(9_000_000))
    }
}
