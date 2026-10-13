// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.app.Activity
import android.app.KeyguardManager
import android.content.Context
import android.hardware.biometrics.BiometricManager.Authenticators.BIOMETRIC_STRONG
import android.hardware.biometrics.BiometricManager.Authenticators.DEVICE_CREDENTIAL
import android.hardware.biometrics.BiometricPrompt
import android.os.Build
import android.os.CancellationSignal
import android.os.SystemClock
import android.view.WindowManager
import android.widget.Switch
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts

/**
 * Confirms the phone's owner with fingerprint, face or the screen-lock PIN,
 * pattern or password. Android performs the check; Saiph receives only success.
 *
 * Used before actions that give another device access (pairing, Hosted
 * enrollment and device requests) and, when the owner turns it on, to open the
 * app. Background sync keys are deliberately not bound to verification, so
 * notifications keep arriving while the phone is locked.
 *
 * Create one per activity as a property: it registers an activity result for
 * Android 8–9, which have no BiometricPrompt with screen-lock fallback.
 */
class AppLock(private val activity: ComponentActivity) {
    companion object {
        /** Leaving Saiph for longer than this locks it again. */
        const val GRACE_MS = 60_000L
        @Volatile private var unlockedAt = 0L
        @Volatile private var backgroundAt = 0L
        fun enabled(context: Context) = context.getSharedPreferences("orion", Context.MODE_PRIVATE).getBoolean("app_lock", false)
        fun deviceSecure(context: Context) = context.getSystemService(KeyguardManager::class.java).isDeviceSecure
        /** True when opening Saiph must ask first. */
        fun locked(context: Context): Boolean {
            if (!enabled(context)) return false
            val now = SystemClock.elapsedRealtime()
            return unlockedAt == 0L || (backgroundAt > unlockedAt && now - backgroundAt > GRACE_MS)
        }
        private fun unlocked() { unlockedAt = SystemClock.elapsedRealtime(); backgroundAt = 0L }
    }

    private var pending: Pair<() -> Unit, (String) -> Unit>? = null
    /** A prompt is open; resuming under it must not open another. */
    var prompting = false
        private set
    /** The owner dismissed the open-app prompt; wait for the Unlock button instead of looping. */
    var declined = false

    private val legacy = activity.registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        prompting = false
        val (success, failure) = pending ?: return@registerForActivityResult
        pending = null
        if (result.resultCode == Activity.RESULT_OK) { unlocked(); success() } else failure("Verification was cancelled. Nothing was changed.")
    }

    /** Call from onStop so a later return after [GRACE_MS] asks again. */
    fun stopped() {
        if (!activity.isChangingConfigurations && !prompting) backgroundAt = SystemClock.elapsedRealtime()
        declined = false
    }

    /** Keep codes, fingerprints and content out of screenshots and the recent-apps preview. */
    fun protectWindow(enabled: Boolean = true) {
        if (enabled) activity.window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        else activity.window.clearFlags(WindowManager.LayoutParams.FLAG_SECURE)
    }

    /**
     * Ask Android to verify the owner, then run [success] on the main thread.
     * With [requireScreenLock], a phone with no screen lock is refused; otherwise
     * it proceeds, because there is nothing Android could verify.
     */
    fun confirm(reason: String, requireScreenLock: Boolean = false, failure: (String) -> Unit = {}, success: () -> Unit) {
        if (prompting) return
        if (!deviceSecure(activity)) {
            if (requireScreenLock) failure("Set a screen lock (fingerprint, face, PIN, pattern or password) on this phone first.")
            else success()
            return
        }
        prompting = true
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val builder = BiometricPrompt.Builder(activity).setTitle("Confirm it's you").setSubtitle(reason)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) builder.setAllowedAuthenticators(BIOMETRIC_STRONG or DEVICE_CREDENTIAL)
            else @Suppress("DEPRECATION") builder.setDeviceCredentialAllowed(true)
            builder.build().authenticate(CancellationSignal(), activity.mainExecutor, object : BiometricPrompt.AuthenticationCallback() {
                override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                    prompting = false; unlocked(); success()
                }
                override fun onAuthenticationError(errorCode: Int, errString: CharSequence) {
                    prompting = false; failure("Verification was cancelled. Nothing was changed.")
                }
            })
        } else {
            @Suppress("DEPRECATION")
            val intent = activity.getSystemService(KeyguardManager::class.java).createConfirmDeviceCredentialIntent("Confirm it's you", reason)
            if (intent == null) { prompting = false; success(); return }
            pending = success to failure
            legacy.launch(intent)
        }
    }

    /** The owner's on/off switch for the open-app lock; changing it needs verification too. */
    fun toggle(): Switch = Switch(activity).apply {
        text = "Require fingerprint, face or PIN to open Saiph"; setTextColor(Palette.TEXT)
        isChecked = enabled(activity)
        setOnCheckedChangeListener { view, checked ->
            if (checked == enabled(activity)) return@setOnCheckedChangeListener
            view.isChecked = !checked // Unchanged until Android confirms the owner.
            confirm(if (checked) "Turn on the Saiph app lock" else "Turn off the Saiph app lock", requireScreenLock = checked,
                failure = { Toast.makeText(activity, it, Toast.LENGTH_LONG).show() }) {
                activity.getSharedPreferences("orion", Context.MODE_PRIVATE).edit().putBoolean("app_lock", checked).apply()
                view.isChecked = checked
            }
        }
    }

    /** Open-app gate for onResume: runs [show] once unlocked, or [lockedScreen] while waiting. */
    fun open(lockedScreen: () -> Unit, show: () -> Unit) {
        if (!locked(activity)) { show(); return }
        lockedScreen()
        if (prompting || declined) return
        confirm("Unlock Saiph", failure = { declined = true }) { show() }
    }
}
