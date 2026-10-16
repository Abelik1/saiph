// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import org.junit.Assert.*
import org.junit.Test

class HostedSharingTest {
    @Test fun firstRequestAndRationaleStillUseAndroidPrompt() {
        assertEquals(HostedSharing.Route.REQUEST, HostedSharing.route(false, false, false, false))
        assertEquals(HostedSharing.Route.REQUEST, HostedSharing.route(false, false, true, true))
    }
    @Test fun permanentDenialAndFullAccessOpenSettingsInsteadOfRepeatingANoop() {
        assertEquals(HostedSharing.Route.SETTINGS, HostedSharing.route(false, false, true, false))
        assertEquals(HostedSharing.Route.SETTINGS, HostedSharing.route(true, false, true, false))
    }
    @Test fun selectedPhotosCanBeReselectedWithoutRequestingFullAccess() {
        assertEquals(HostedSharing.Route.REQUEST, HostedSharing.route(false, true, true, false))
    }
    @Test fun sharingSetupIsOnlyOfferedAfterApprovalAndOnlyUntilCompleted() {
        assertFalse(HostedSharing.needsSetup(false, false))
        assertTrue(HostedSharing.needsSetup(true, false))
        assertFalse(HostedSharing.needsSetup(true, true))
    }
}
