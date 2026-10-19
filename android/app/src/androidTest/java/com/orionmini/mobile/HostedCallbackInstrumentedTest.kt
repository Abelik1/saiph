// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.content.Intent
import android.net.Uri
import android.content.pm.PackageManager
import android.app.Activity
import android.os.Bundle
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import net.openid.appauth.*
import org.junit.Assert.*
import org.junit.After
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

/** Synthetic callbacks only; never exchanges a code or opens a real account. */
@RunWith(AndroidJUnit4::class)
class HostedCallbackInstrumentedTest {
    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext
    private val prefs get() = context.getSharedPreferences("orion_hosted", 0)
    private val account get() = HostedAccount.get(context)

    @Before fun configure() {
        assertFalse("Use a fresh isolated profile", prefs.contains("device_id"))
        assertFalse("No live account permitted", account.signedIn())
        prefs.edit().clear().putBoolean("enabled", true).putString("issuer", "https://synthetic.auth0.com/")
            .putString("audience", "synthetic-api").putString("client_id", "synthetic-native").commit()
    }
    @After fun cleanup() { account.cancel(); prefs.edit().clear().commit() }

    private fun response(request: AuthorizationRequest, state: String? = request.state): AuthorizationResponse =
        AuthorizationResponse.Builder(request).setState(state).setAuthorizationCode("synthetic-code").build()
    private fun reject(value: AuthorizationResponse) {
        try { account.consume(value); fail("Unbound callback must be rejected before token exchange") }
        catch (_: IllegalStateException) { }
    }
    private fun altered(request: AuthorizationRequest, redirect: String = request.redirectUri.toString(),
                        client: String = request.clientId, configuration: AuthorizationServiceConfiguration = request.configuration,
                        verifier: String? = request.codeVerifier): AuthorizationRequest =
        AuthorizationRequest.Builder(configuration, client, ResponseTypeValues.CODE, Uri.parse(redirect))
            .setState(request.state).setCodeVerifier(verifier).build()

    @Test fun httpsAttemptIsBoundToStatePkceAndSingleUse() {
        val request = account.request()
        assertEquals("https://usesaiph.com/android/oauth2redirect", request.redirectUri.toString())
        assertEquals("google-oauth2", request.additionalParameters["connection"])
        assertEquals("S256", request.codeVerifierChallengeMethod)
        reject(response(request, "wrong-state"))
        reject(response(altered(request, redirect = "com.orionmini.mobile.hosted:/oauth2redirect")))
        reject(response(altered(request, redirect = "https://usesaiph.com/android/oauth2redirect/extra")))
        reject(response(altered(request, client = "different-client")))
        reject(response(altered(request, verifier = CodeVerifierUtil.generateRandomCodeVerifier())))
        reject(response(altered(request, verifier = null)))
        reject(response(altered(request, configuration = AuthorizationServiceConfiguration(
            Uri.parse("https://different.invalid/authorize"), request.configuration.tokenEndpoint))))
        reject(response(altered(request, configuration = AuthorizationServiceConfiguration(
            request.configuration.authorizationEndpoint, Uri.parse("https://different.invalid/token")))))
        assertEquals(request.state, prefs.getString("pending_state", null))
        // Same checks apply after recreating the account around persisted attempt metadata.
        val constructor = HostedAccount::class.java.getDeclaredConstructor(android.content.Context::class.java).apply { isAccessible = true }
        val restored = constructor.newInstance(context)
        restored.consume(response(request))
        reject(response(request))
        assertFalse(prefs.contains("pending_redirect"))
        assertFalse(prefs.contains("pending_pkce"))
        assertFalse(account.signedIn()) // Accepting the callback alone never creates a session.
    }

    @Test fun supersededCancelledExpiredAndUnsolicitedCallbacksCannotSignIn() {
        val previous = account.request()
        val current = account.request()
        reject(response(previous))
        assertEquals(current.state, prefs.getString("pending_state", null))
        account.cancel()
        reject(response(current))
        val expired = account.request()
        prefs.edit().putLong("pending_until", System.currentTimeMillis() - 1).commit()
        reject(response(expired))
        account.cancel()
        reject(response(expired))
        assertFalse(account.signedIn())
    }

    @Test fun onlyAnExistingPreUpgradeAttemptCanFinishOnTheLegacyScheme() {
        val legacy = AuthorizationRequest.Builder(account.configuration(), "synthetic-native", ResponseTypeValues.CODE,
            Uri.parse("com.orionmini.mobile.hosted:/oauth2redirect")).build()
        prefs.edit().putString("pending_state", legacy.state).putLong("pending_until", System.currentTimeMillis() + 60_000).commit()
        account.consume(response(legacy))
        reject(response(legacy))
        val fresh = account.request()
        reject(response(altered(fresh, redirect = legacy.redirectUri.toString())))
        account.consume(response(fresh))
    }

    @Test fun mergedManifestHandlesOnlyTheExactHttpsCallbackAndRetainsLegacy() {
        fun receivers(url: String) = context.packageManager.queryIntentActivities(
            Intent(Intent.ACTION_VIEW, Uri.parse(url)).addCategory(Intent.CATEGORY_BROWSABLE).setPackage(context.packageName),
            PackageManager.MATCH_DEFAULT_ONLY).map { it.activityInfo.name }
        val receiver = "net.openid.appauth.RedirectUriReceiverActivity"
        assertEquals(listOf(receiver), receivers(HostedAccount.REDIRECT + "?code=synthetic&state=synthetic"))
        assertEquals(listOf(receiver), receivers("com.orionmini.mobile.hosted:/oauth2redirect?code=synthetic"))
        for (url in listOf("https://usesaiph.com/", "https://usesaiph.com/android/oauth2redirect/extra",
            "https://www.usesaiph.com/android/oauth2redirect", "https://usesaiph.com.evil.invalid/android/oauth2redirect",
            "http://usesaiph.com/android/oauth2redirect")) assertTrue(url, receivers(url).isEmpty())
    }

    @Test fun preUpgradeBrowserResultStillReachesSignInAfterAddingPermissionsLauncher() {
        // Restore the launch key used by the previous APK. Cancellation needs no
        // token exchange and demonstrates which callback receives the result.
        prefs.edit().putBoolean("enabled", false).commit()
        AppPolicy.acknowledge(context)
        ActivityScenario.launch(HostedActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                val registry = activity.activityResultRegistry
                val saved = Bundle()
                registry.onSaveInstanceState(saved)
                val keys = saved.getStringArrayList("KEY_COMPONENT_ACTIVITY_REGISTERED_KEYS")!!
                val codes = saved.getIntegerArrayList("KEY_COMPONENT_ACTIVITY_REGISTERED_RCS")!!
                val originalLoginKey = "activity_rq#1" // AppLock, then sign-in in the previous APK.
                val index = keys.indexOf(originalLoginKey)
                assertTrue(index >= 0)
                saved.putStringArrayList("KEY_COMPONENT_ACTIVITY_LAUNCHED_KEYS", arrayListOf(originalLoginKey))
                registry.onRestoreInstanceState(saved)
                assertTrue(registry.dispatchResult(codes[index], Activity.RESULT_CANCELED, Intent()))
                fun hasLoginError(view: View): Boolean =
                    (view is TextView && view.text.contains("Sign-in did not complete")) ||
                        (view is ViewGroup && (0 until view.childCount).any { hasLoginError(view.getChildAt(it)) })
                assertTrue("A pending browser result must reach sign-in, not the permission callback", hasLoginError(activity.window.decorView))
            }
        }
    }
}
