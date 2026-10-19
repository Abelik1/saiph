// SPDX-License-Identifier: GPL-3.0-only
package sefirah.network.orion

import org.junit.Assert.*
import org.junit.Test

class HostedClipboardImagesTest {
    @Test fun dimensionBoundsUseLongArithmeticBeforeDecode() {
        assertTrue(HostedClipboardImages.dimensions(4000, 4000))
        assertFalse(HostedClipboardImages.dimensions(4001, 4000))
        assertFalse(HostedClipboardImages.dimensions(Int.MAX_VALUE, Int.MAX_VALUE))
        assertFalse(HostedClipboardImages.dimensions(0, 10))
        assertFalse(HostedClipboardImages.dimensions(10, -1))
        assertEquals(setOf("image/png", "image/jpeg", "image/webp"), HostedClipboardImages.extensions.keys)
    }
}
