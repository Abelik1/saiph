// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import org.junit.Assert.*
import org.junit.Test

class HostedSignInTest {
    @Test fun googleRoutingPreservesTheSaiphAudience() {
        assertEquals(mapOf("audience" to "https://synthetic.invalid/api", "connection" to "google-oauth2"),
            HostedSignIn.parameters("https://synthetic.eu.auth0.com/", "https://synthetic.invalid/api"))
        assertEquals("select_account", HostedSignIn.prompt("https://synthetic.eu.auth0.com/"))
    }
    @Test fun emailRoutingOpensTheEmailFormWithTheSaiphAudience() {
        assertEquals(mapOf("audience" to "https://synthetic.invalid/api", "connection" to "Username-Password-Authentication"),
            HostedSignIn.parameters("https://synthetic.eu.auth0.com/", "https://synthetic.invalid/api", HostedSignIn.Method.EMAIL))
        assertEquals("login", HostedSignIn.prompt("https://synthetic.eu.auth0.com/", HostedSignIn.Method.EMAIL))
    }
    @Test fun existingAccountsCanKeepTheirOriginalSignInMethod() {
        assertEquals(mapOf("audience" to "original-audience"),
            HostedSignIn.parameters("https://synthetic.eu.auth0.com/", "original-audience", HostedSignIn.Method.ANY))
        assertNull(HostedSignIn.prompt("https://synthetic.eu.auth0.com/", HostedSignIn.Method.ANY))
    }
    @Test fun customAndLookalikeIssuersDoNotReceiveAuth0ProviderParameters() {
        for (issuer in listOf("https://auth.synthetic.invalid/", "https://auth0.com.evil.invalid/", "https://notauth0.com/"))
            for (method in HostedSignIn.Method.entries) {
                assertEquals(mapOf("audience" to "synthetic-audience"), HostedSignIn.parameters(issuer, "synthetic-audience", method))
                assertNull(HostedSignIn.prompt(issuer, method))
            }
    }
    /** AppAuth throws IllegalArgumentException for these in setAdditionalParameters (0.9.9 shipped one). */
    @Test fun extraParametersNeverRepeatOnesAppAuthBuildsItself() {
        val builtIn = setOf("client_id", "code_challenge", "code_challenge_method", "display", "login_hint", "prompt",
            "ui_locales", "redirect_uri", "response_mode", "response_type", "scope", "state", "claims", "claims_locales", "nonce",
            "request", "request_uri")
        for (method in HostedSignIn.Method.entries)
            assertTrue(HostedSignIn.parameters("https://synthetic.eu.auth0.com/", "synthetic-audience", method).keys.none { it in builtIn })
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
