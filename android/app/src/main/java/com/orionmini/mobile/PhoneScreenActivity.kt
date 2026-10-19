// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.media.projection.MediaProjectionConfig
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.widget.LinearLayout
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts

/**
 * Show this phone's screen on a computer (docs/PHONE_SCREEN.md). The offer comes from a
 * Saiph Cloud notification or a scanned QR. Starting needs owner verification and then
 * Android's own capture prompt, every session. Control from the computer is a separate,
 * opt-in Android accessibility service explained here; without it the session is view only.
 */
class PhoneScreenActivity : ComponentActivity() {
    companion object {
        /** Only the offer ID travels in the notification's intent; the invitation stays in memory. */
        const val EXTRA_OFFER = "session_offer"
        private const val PREFS = "orion_hosted"
        private const val OFFERS = "screen_offers"
        /** Approved computers may offer sessions and list apps over Saiph Cloud (owner switch). */
        fun offersAllowed(context: Context) = context.getSharedPreferences(PREFS, 0).getBoolean(OFFERS, true)
    }
    private val lock = AppLock(this)
    private lateinit var root: LinearLayout
    private lateinit var frame: ScreenFrame
    private var code: String? = null
    /** Allow was chosen in the request pop-up or notification: verify once this page is resumed. */
    private var confirmAfterResume = false
    private var resumed = false
    private var label = ""
    private var explaining = false
    private val scan = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        val scanned = result.data?.getStringExtra(OrionQrActivity.SCREEN_CODE) ?: return@registerForActivityResult
        accept(scanned, "your computer")
    }
    private val consent = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        val current = code
        val data = result.data
        if (result.resultCode != Activity.RESULT_OK || data == null || current == null) { show("Sharing was not started."); return@registerForActivityResult }
        if (runCatching { ScreenOffer.parse(current) }.isFailure) { code = null; show("That request expired. Start again on your computer."); return@registerForActivityResult }
        ScreenShareService.start(this, current, result.resultCode, data)
        code = null
        // Saiph's own windows are protected (black on the computer), so show the home screen;
        // an offered app opens on top once the computer receives the first picture.
        startActivity(Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        finish()
    }

    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        lock.protectWindow()
        window.statusBarColor = Palette.BG; window.navigationBarColor = Palette.BG
        if (!AppPolicy.acknowledged(this)) { finish(); return }
        page()
        intent?.let(::fromIntent)
    }

    override fun onNewIntent(intent: Intent) { super.onNewIntent(intent); fromIntent(intent) }

    /** The shared frame: Back in the top corner, the title, then this state's content. */
    private fun page() {
        frame = ScreenFrame(this, if (explaining) "Control from computer" else "Phone screen",
            back = { if (explaining) { explaining = false; show() } else finish() })
        root = frame.content
    }

    private fun fromIntent(intent: Intent) {
        val id = intent.getStringExtra(EXTRA_OFFER) ?: return
        val allow = intent.getBooleanExtra(RequestPrompts.EXTRA_ALLOW, false)
        intent.removeExtra(EXTRA_OFFER); intent.removeExtra(RequestPrompts.EXTRA_ALLOW)
        RequestPrompts.taken(this, "screen")
        // Taken once: a second tap or a replayed notification finds nothing.
        val pending = SessionOffers.take(id)?.takeIf { it.offer.service == "screen" }
        if (pending == null) { code = null; show("That request expired. Start again on your computer."); return }
        accept(pending.offer.invite, pending.computer)
        // Allow in the pop-up or notification goes straight to confirming it's you.
        if (allow) { if (resumed && !AppLock.locked(this)) confirmStart() else confirmAfterResume = true }
    }

    /** Owner verification (screen lock required), then Android's own capture prompt. */
    private fun confirmStart() {
        if (code == null) return
        lock.confirm("Show your phone screen on $label", requireScreenLock = true, failure = { show(it) }) { requestConsent() }
    }

    private fun accept(value: String, name: String) {
        if (runCatching { ScreenOffer.parse(value) }.isFailure) { code = null; show("That request expired. Start again on your computer."); return }
        code = value; label = name.take(40).ifBlank { "your computer" }; explaining = false; show()
    }

    override fun onResume() {
        super.onResume(); resumed = true
        lock.open(lockedScreen = { page(); root.addView(text("Confirm it's you to open Saiph.", UiType.BODY, Palette.MUTED))
            frame.dockActions(button("Unlock", true) { lock.declined = false; lock.open({}, { show() }) }) }, show = {
            show()
            if (confirmAfterResume) { confirmAfterResume = false; confirmStart() }
        })
    }
    override fun onPause() { resumed = false; super.onPause() }
    override fun onStop() { lock.stopped(); super.onStop() }

    private fun show(message: String? = null) {
        if (!::root.isInitialized) return
        page()
        if (explaining) { explanation(); return }
        // Live: a red banner while this phone's screen is showing on a computer.
        if (ScreenShareService.active()) root.addView(liveBanner("Your screen is showing on your computer."))
        val status: TextView = text(message ?: when {
            ScreenShareService.active() -> "Stop here or from the notification. Locking the phone also stops sharing."
            code != null -> "Show your phone screen on $label? Your computer sees everything on this screen until you stop. " +
                "Protected screens, such as passwords and banking apps, stay black. Nothing is recorded and there is no sound. " +
                "Locking the phone stops sharing."
            else -> "On your computer, open Saiph → Phone → Apps and choose Show phone screen."
        }, UiType.BODY, Palette.MUTED).apply { setPadding(dp(2), dp(4), 0, dp(20)) }
        root.addView(status)
        when {
            ScreenShareService.active() -> root.addView(button("Stop sharing", tone = Tone.DANGER) { ScreenShareService.stop(this); show("Sharing stopped.") })
            code != null -> {
                root.addView(button("Start sharing", true) { confirmStart() })
                root.addView(button("Not now") { code = null; show() })
            }
            else -> root.addView(button("Scan computer's code", tone = Tone.TONAL) {
                if (!AppLock.locked(this)) scan.launch(OrionQrActivity.screenSession(this))
            })
        }
        root.addView(section("Control from computer"))
        val on = SaiphInputService.enabled(this)
        root.addView(body(if (on) "On. During a session your computer can tap, swipe, type and press Back, Home and Recents."
            else "Off. Sessions are view only. Turn this on to use your phone with the computer's mouse and keyboard."))
        root.addView(button(if (on) "Turn off in Android settings" else "Turn on control from computer", tone = Tone.TONAL) {
            if (on) openAccessibility() else { explaining = true; show() }
        })
        root.addView(switchRow("Let my computers offer sessions", "Approved computers on Saiph Cloud can send a request and list your apps. You still decide each time.",
            offersAllowed(this)) { allowed -> getSharedPreferences(PREFS, 0).edit().putBoolean(OFFERS, allowed).apply() })
    }

    /** The opt-in explanation Android's accessibility consent follows. */
    private fun explanation() {
        root.addView(body("Saiph uses an Android accessibility service so your computer's mouse and keyboard can tap, swipe and type on this phone " +
            "while you show your screen.").apply { setPadding(0, dp(16), 0, dp(8)) })
        root.addView(body("It works only during a phone screen session you started, which shows a notification with Stop. Saiph does not read, " +
            "store or send what is on your screen through this service; the screen picture uses Android's own screen sharing.").apply { setPadding(0, 0, 0, dp(8)) })
        root.addView(body("On the next screen, choose Saiph phone screen control and turn it on. You can turn it off there at any time.")
            .apply { setPadding(0, 0, 0, dp(20)) })
        root.addView(button("Open Android settings", true) { explaining = false; openAccessibility() })
        root.addView(button("Not now") { explaining = false; show() })
    }

    private fun openAccessibility() = startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))

    /** Android shows its capture prompt each session; on Android 14+ it is limited to the whole screen, one step. */
    private fun requestConsent() {
        val manager = getSystemService(MediaProjectionManager::class.java)
        consent.launch(if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE)
            manager.createScreenCaptureIntent(MediaProjectionConfig.createConfigForDefaultDisplay())
        else manager.createScreenCaptureIntent())
    }
}
