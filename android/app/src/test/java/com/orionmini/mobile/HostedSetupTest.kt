// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import org.junit.Assert.assertEquals
import org.junit.Test

class HostedSetupTest {
    @Test fun accountAndDeviceIntentDoNotImplyApproval() {
        assertEquals(HostedSetup.Stage.SCAN, HostedSetup.stage(false, false, false))
        assertEquals(HostedSetup.Stage.APPROVAL, HostedSetup.stage(true, false, false))
        assertEquals(HostedSetup.Stage.RECOVERY, HostedSetup.stage(true, true, false))
    }
    @Test fun verifiedApprovalSurvivesTemporarySignOutButMissingKeysNeedRecovery() {
        assertEquals(HostedSetup.Stage.HOME, HostedSetup.stage(true, false, true))
        assertEquals(HostedSetup.Stage.RECOVERY, HostedSetup.stage(true, true, true))
        assertEquals(HostedSetup.Stage.SCAN, HostedSetup.stage(false, false, true))
    }
    @Test fun interruptedRequestsRetryWithoutReenrollingApprovedDevices() {
        org.junit.Assert.assertTrue(HostedSetup.retryEnrollment(false, 0, 100))
        org.junit.Assert.assertFalse(HostedSetup.retryEnrollment(false, 100, 30_099))
        org.junit.Assert.assertTrue(HostedSetup.retryEnrollment(false, 100, 30_100))
        org.junit.Assert.assertFalse(HostedSetup.retryEnrollment(true, 0, 100_000))
    }
}
