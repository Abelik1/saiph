package com.orionmini.mobile

import android.content.Intent
import android.widget.Button
import android.widget.TextView
import androidx.lifecycle.lifecycleScope
import com.castle.sefirah.BuildConfig
import com.google.firebase.appdistribution.FirebaseAppDistribution
import com.google.firebase.appdistribution.UpdateStatus
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** Firebase tester login is independent of Orion pairing. Never log SDK/account errors. */
class AppUpdates(private val activity: OrionActivity) {
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

    fun checkManual(button: Button, status: TextView) {
        if (busy) { status.text = "An update check is already running."; return }
        busy = true; button.isEnabled = false; status.text = "Checking for updates…"
        fun finish(message: String) {
            busy = false
            if (!activity.isFinishing && !activity.isDestroyed) {
                button.isEnabled = true; status.text = message
            }
        }
        activity.lifecycleScope.launch {
            // Preserve the signed mesh updater, including when Firebase is unavailable.
            val hub = withContext(Dispatchers.IO) {
                try { Result.success(Updater.latest(activity)) }
                catch (cancelled: CancellationException) { throw cancelled }
                catch (_: Exception) { Result.failure<org.json.JSONObject?>(IllegalStateException("Update check unavailable")) }
            }
            if (activity.isFinishing || activity.isDestroyed) { busy = false; return@launch }
            val release = hub.getOrNull()
            if (release != null && Updater.isNewer(release)) {
                finish("Update available: ${Updater.label(release)}")
                activity.startActivity(Intent(activity, UpdateActivity::class.java))
                return@launch
            }
            val current = hub.isSuccess
            if (!BuildConfig.HAS_APP_DISTRIBUTION) {
                finish(if (current) "You're on the latest available version." else "Couldn't check for updates. Try again when online.")
                return@launch
            }
            runCatching {
                FirebaseAppDistribution.getInstance().updateIfNewReleaseAvailable()
                    .addOnProgressListener { progress ->
                        if (!activity.isDestroyed) status.text = when (progress.updateStatus) {
                            UpdateStatus.DOWNLOADING -> "Downloading update… Android will ask you to confirm installation."
                            UpdateStatus.NEW_RELEASE_NOT_AVAILABLE -> "You're on the latest available version."
                            else -> "Preparing update…"
                        }
                    }
                    .addOnSuccessListener { finish(if (status.text == "You're on the latest available version.") status.text.toString() else "Update check complete.") }
                    .addOnFailureListener {
                        finish(if (current) "Installed version is current. Firebase check unavailable; automatic checks continue."
                            else "Couldn't check for updates. Try again when online or use Firebase App Tester.")
                    }
            }.onFailure { finish("Update service unavailable. Automatic checks continue.") }
        }
    }
}
