// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import org.junit.Assert.*
import org.junit.Test

class HostedSignInTest {
    @Test fun googleRoutingPreservesTheSaiphAudience() {
        assertEquals(mapOf("audience" to "https://synthetic.invalid/api", "connection" to "google-oauth2", "prompt" to "select_account"),
            HostedSignIn.parameters("https://synthetic.eu.auth0.com/", "https://synthetic.invalid/api"))
    }
    @Test fun emailRoutingOpensTheEmailFormWithTheSaiphAudience() {
        assertEquals(mapOf("audience" to "https://synthetic.invalid/api", "connection" to "Username-Password-Authentication", "prompt" to "login"),
            HostedSignIn.parameters("https://synthetic.eu.auth0.com/", "https://synthetic.invalid/api", HostedSignIn.Method.EMAIL))
    }
    @Test fun existingAccountsCanKeepTheirOriginalSignInMethod() {
        assertEquals(mapOf("audience" to "original-audience"),
            HostedSignIn.parameters("https://synthetic.eu.auth0.com/", "original-audience", HostedSignIn.Method.ANY))
    }
    @Test fun customAndLookalikeIssuersDoNotReceiveAuth0ProviderParameters() {
        for (issuer in listOf("https://auth.synthetic.invalid/", "https://auth0.com.evil.invalid/", "https://notauth0.com/"))
            for (method in HostedSignIn.Method.entries)
                assertEquals(mapOf("audience" to "synthetic-audience"), HostedSignIn.parameters(issuer, "synthetic-audience", method))
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
