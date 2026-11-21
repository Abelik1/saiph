package com.orionmini.mobile

import org.junit.After
import org.junit.Assert.*
import org.junit.Test

class CameraAskTest {
    @After fun reset() = CameraAsk.cancel()

    @Test fun onlyTheAskedComputerAnswersAndOnlyOnce() {
        CameraAsk.ask("desk", now = 1000)
        assertFalse(CameraAsk.answers("laptop", now = 1001))
        assertTrue(CameraAsk.answers("desk", now = 1001))
        assertFalse(CameraAsk.answers("desk", now = 1002))
    }

    @Test fun anUnansweredRequestLapsesAndCancelForgetsIt() {
        CameraAsk.ask("desk", now = 1000)
        assertFalse(CameraAsk.answers("desk", now = 1000 + CameraAsk.WAIT_SECONDS))
        CameraAsk.ask("desk", now = 2000)
        CameraAsk.cancel()
        assertFalse(CameraAsk.answers("desk", now = 2001))
    }
}
