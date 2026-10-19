// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.google.crypto.tink.integration.android.AndroidKeystore
import net.openid.appauth.*
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

/** Synthetic grants and real Android Keystore only. Never contacts an identity provider. */
@RunWith(AndroidJUnit4::class)
class HostedAccountInstrumentedTest {
    @Test fun protectedSessionSurvivesAccountRecreationAndRotatesAtomically() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val prefs = context.getSharedPreferences("orion_hosted", 0)
        assertFalse("Fresh isolated profile required", prefs.contains("device_id"))
        assertFalse("No live session permitted", HostedAccount.get(context).signedIn())
        val file = File(context.noBackupFilesDir, "hosted-refresh.enc")
        assertFalse(file.exists())
        val constructor = HostedAccount::class.java.getDeclaredConstructor(android.content.Context::class.java).apply { isAccessible = true }
        prefs.edit().clear().putBoolean("enabled", true).putBoolean("refresh_tokens", true)
            .putString("issuer", "https://synthetic.invalid/").putString("audience", "synthetic-api").putString("client_id", "synthetic-native").commit()
        try {
            val first = constructor.newInstance(context)
            fun grant(account: HostedAccount, refresh: String?): Pair<TokenResponse, Int> {
                val request = account.request()
                assertEquals("offline_access", request.scope)
                val response = AuthorizationResponse.Builder(request).setState(request.state).setAuthorizationCode("synthetic-code").build()
                val epoch = account.consume(response)
                return TokenResponse.Builder(response.createTokenExchangeRequest()).setTokenType("Bearer")
                    .setAccessToken("synthetic-access").setAccessTokenExpirationTime(System.currentTimeMillis() + 3_600_000)
                    .setRefreshToken(refresh).build() to epoch
            }
            val (initial, epoch) = grant(first, "synthetic-refresh-one")
            first.accept(initial, epoch, true)
            val encrypted = file.readBytes()
            assertFalse(String(encrypted).contains("synthetic-refresh-one"))
            val restored = constructor.newInstance(context)
            assertTrue(restored.signedIn()) // No in-memory access token on this instance.
            val (rotated, next) = grant(restored, "synthetic-refresh-two")
            restored.accept(rotated, next, true)
            assertFalse(encrypted.contentEquals(file.readBytes()))
            val binding = listOf("Orion/hosted-account/v1", "https://synthetic.invalid/", "synthetic-api", "synthetic-native").joinToString("\u0000").toByteArray()
            assertEquals("synthetic-refresh-two", String(AndroidKeystore.getAead("orion_hosted_account_v1").decrypt(file.readBytes(), binding)))
            val retained = file.readBytes()
            val (missing, missingEpoch) = grant(restored, null)
            try { restored.accept(missing, missingEpoch, true); fail("Rotation must return its replacement") }
            catch (failure: HostedSignInException) { assertEquals(HostedSignInIssue.PERSISTENT_SESSION, failure.issue) }
            assertArrayEquals(retained, file.readBytes())
            assertTrue(constructor.newInstance(context).signedIn())
            prefs.edit().putBoolean("signed_out", true).commit()
            assertFalse(constructor.newInstance(context).signedIn())
        } finally {
            file.delete()
            prefs.edit().clear().commit()
        }
    }
}
