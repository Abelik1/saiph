// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import org.junit.Assert.*
import org.junit.Test
import kotlinx.serialization.json.*

class HostedAccountAccessTest {
    @Test fun signInRequestsVerifiedEmailWithoutLosingRefreshTokens() {
        assertEquals("openid email", HostedSignIn.scope(false))
        assertEquals("openid email offline_access", HostedSignIn.scope(true))
    }
    @Test fun customDeploymentsNeverSendTheirTokensToThePackagedAccountSite() {
        val defaults = buildJsonObject {
            put("service_url", "https://cloud.example.test/"); put("issuer", "https://synthetic.auth0.com/")
            put("audience", "https://aud.example.test"); put("android_client_id", "synthetic_android")
        }
        val correct = listOf("https://cloud.example.test", "https://synthetic.auth0.com/", "https://aud.example.test", "synthetic_android")
        fun matches(values: List<String>) = HostedAccountAccess.matchesDeployment(defaults, values[0], values[1], values[2], values[3])
        assertTrue(matches(correct))
        for (index in correct.indices) assertFalse(matches(correct.mapIndexed { i, value -> if (i == index) "other" else value }))
        assertFalse(HostedAccountAccess.matchesDeployment(buildJsonObject {}, correct[0], correct[1], correct[2], correct[3]))
    }
}
