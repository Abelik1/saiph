package com.orionmini.mobile

import com.castle.sefirah.BuildConfig
import com.google.firebase.appdistribution.FirebaseAppDistribution

/**
 * Firebase tester login is independent of Orion pairing. Never log SDK/account errors.
 * Checking, downloading and installing from the Hub or Saiph account is [UpdateController];
 * Settings opens [UpdateActivity], which also offers Firebase App Tester when that is the source.
 */
class AppUpdates(@Suppress("unused") private val activity: OrionActivity) {
    private var startupChecked = false
    private var busy = false

    fun checkStartup() {
        if (startupChecked || busy || !BuildConfig.HAS_APP_DISTRIBUTION) return
        startupChecked = true
        // No recurring sign-in prompt. The Settings button enables Firebase alerts once.
        runCatching {
            val sdk = FirebaseAppDistribution.getInstance()
            if (sdk.isTesterSignedIn) {
                busy = true
                sdk.updateIfNewReleaseAvailable().addOnCompleteListener { busy = false }
            }
        }.onFailure { busy = false }
    }
}
