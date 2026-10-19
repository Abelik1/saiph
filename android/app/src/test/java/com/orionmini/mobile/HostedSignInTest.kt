// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import org.junit.Assert.*
import org.junit.Test

class HostedSignInTest {
    @Test fun googleRoutingPreservesTheSaiphAudience() {
        assertEquals(mapOf("audience" to "https://synthetic.invalid/api", "connection" to "google-oauth2"),
            HostedSignIn.parameters("https://synthetic.eu.auth0.com/", "https://synthetic.invalid/api"))
    }
    @Test fun existingAccountsCanKeepTheirOriginalSignInMethod() {
        assertEquals(mapOf("audience" to "original-audience"),
            HostedSignIn.parameters("https://synthetic.eu.auth0.com/", "original-audience", google = false))
    }
    @Test fun customAndLookalikeIssuersDoNotReceiveAuth0ProviderParameters() {
        for (issuer in listOf("https://auth.synthetic.invalid/", "https://auth0.com.evil.invalid/", "https://notauth0.com/"))
            assertFalse(HostedSignIn.parameters(issuer, "synthetic-audience").containsKey("connection"))
    }
    @Test fun untrustedFailureTextCannotReachTheSignInNotice() {
        val privateBody = "synthetic-token https://synthetic.invalid/callback?code=private-code"
        val issue = HostedSignIn.issue(IllegalStateException(privateBody))
        assertEquals(HostedSignInIssue.UNAVAILABLE, issue)
        assertFalse(issue.message.contains("synthetic-token"))
        assertFalse(issue.message.contains("private-code"))
        assertFalse(issue.message.contains("https://"))
    }
}
