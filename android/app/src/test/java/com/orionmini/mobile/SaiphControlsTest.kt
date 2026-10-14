// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import org.junit.Assert.assertEquals
import org.junit.Test

class SaiphControlsTest {
    @Test
    fun everyStateHasAWidgetLineAndATileWord() {
        // The tile subtitle and the small widget only have room for one or two words.
        for (state in SaiphControls.State.values()) {
            assert(SaiphControls.status(state).isNotBlank())
            assert(SaiphControls.short(state).split(" ").size <= 2)
        }
        assertEquals("Paused", SaiphControls.short(SaiphControls.State.PAUSED))
        assertEquals("Paused · nothing syncs", SaiphControls.status(SaiphControls.State.PAUSED))
        assertEquals("Connected", SaiphControls.short(SaiphControls.State.HOSTED))
        assertEquals("Reconnecting", SaiphControls.short(SaiphControls.State.RECONNECTING))
    }

    @Test
    fun computerNamesFitTheRingButton() {
        assertEquals("Orion desktop", SaiphControls.shortName("Orion desktop (AlexMainDesktop)"))
        assertEquals("Laptop", SaiphControls.shortName("Laptop"))
        assertEquals("A very long com…", SaiphControls.shortName("A very long computer name"))
        assertEquals("(Odd)", SaiphControls.shortName("(Odd)"))
    }
}
