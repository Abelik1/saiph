// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import org.junit.Assert.*
import org.junit.Test

class HostedTransferTextTest {
    @Test fun limitMatchesTheDesktopAndRelay() {
        // MAX_CIPHERTEXT (20 MiB) less the sealed stream's 4 KiB, as in hosted_transfers.py.
        assertEquals(20_967_424L, HostedTransferText.MAX_PLAINTEXT)
        assertEquals("19.9", HostedTransferText.megabytes(HostedTransferText.MAX_PLAINTEXT))
    }

    @Test fun oversizeIsRefusedBeforeEncryptionWithBothSizes() {
        HostedTransferText.checkSize(HostedTransferText.MAX_PLAINTEXT)
        HostedTransferText.checkSize(null)  // Unknown size: the bounded reader still enforces the limit.
        val refused = assertThrows(TransferRefused::class.java) { HostedTransferText.checkSize(25L * 1_048_576) }
        assertEquals("Saiph Cloud sends files up to 19.9 MB. This file is 25.0 MB. Nothing was sent.", refused.message)
        // Just over the limit never reads as "19.9 MB".
        val edge = assertThrows(TransferRefused::class.java) { HostedTransferText.checkSize(HostedTransferText.MAX_PLAINTEXT + 1) }
        assertTrue(edge.message!!.contains("This file is 20.0 MB."))
    }

    @Test fun confirmationsNameTheFileAndDevice() {
        assertEquals("Sent report.pdf to Synthetic laptop.", HostedTransferText.sent(listOf("report.pdf"), "Synthetic laptop"))
        assertEquals("Sent 3 files to Synthetic laptop.", HostedTransferText.sent(listOf("a", "b", "c"), "Synthetic laptop"))
        assertEquals("Saved photo (1).jpg in Downloads → Saiph.", HostedTransferText.saved("photo (1).jpg"))
    }
}
