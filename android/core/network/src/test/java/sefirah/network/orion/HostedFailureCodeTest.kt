// SPDX-License-Identifier: GPL-3.0-only
package sefirah.network.orion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** Failure counts carry a fixed reason only; mirrors the desktop's hosted_transport.failure_code. */
class HostedFailureCodeTest {
    @Test fun sealedRoutesMapToThePublishedReasons() {
        assertEquals("hosted_send_failed", HostedHttpTransport.failureCode("POST", "/v1/sealed/events"))
        assertEquals("hosted_receive_failed", HostedHttpTransport.failureCode("GET", "/v1/sealed/events"))
        assertEquals("file_send_failed", HostedHttpTransport.failureCode("POST", "/v1/sealed/blobs"))
        assertEquals("file_send_failed", HostedHttpTransport.failureCode("POST", "/v1/sealed/blobs/00000000-0000-4000-8000-000000000000/chunks/3"))
        assertEquals("file_receive_failed", HostedHttpTransport.failureCode("GET", "/v1/sealed/blobs/00000000-0000-4000-8000-000000000000/chunks/0"))
    }

    @Test fun otherRoutesAreNotCounted() {
        assertNull(HostedHttpTransport.failureCode("DELETE", "/v1/sealed/events/00000000-0000-4000-8000-000000000000"))
        assertNull(HostedHttpTransport.failureCode("GET", "/v1/devices/rosters"))
        assertNull(HostedHttpTransport.failureCode("GET", "/v1/access"))
    }
}
