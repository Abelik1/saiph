// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

/** UI state, separate from token availability and transport status strings. */
internal object HostedSetup {
    enum class Stage { SCAN, APPROVAL, RECOVERY, HOME }
    fun stage(hasIdentity: Boolean, identityUnavailable: Boolean, approvalVerified: Boolean) = when {
        !hasIdentity -> Stage.SCAN
        identityUnavailable -> Stage.RECOVERY
        approvalVerified -> Stage.HOME
        else -> Stage.APPROVAL
    }
    fun retryEnrollment(approvalVerified: Boolean, lastAttempt: Long, now: Long) =
        !approvalVerified && (lastAttempt == 0L || now - lastAttempt >= 30_000L)
}
