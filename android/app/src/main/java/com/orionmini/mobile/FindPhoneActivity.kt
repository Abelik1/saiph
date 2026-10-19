// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.app.KeyguardManager
import android.os.Build
import android.os.Bundle
import android.view.Gravity
import android.view.KeyEvent
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.activity.OnBackPressedCallback
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import sefirah.network.orion.FindPhoneRing
import sefirah.network.orion.OrionRing

/**
 * The full-screen Stop for "Find phone", shown over the lock screen while the phone rings.
 * It shows only who asked; nothing else from Saiph is visible and nothing needs unlocking.
 * Stop, Back, a volume key or the power button stop the ring; the screen closes when the
 * ring ends anywhere (the notification's Stop, time running out).
 */
class FindPhoneActivity : ComponentActivity() {
    private lateinit var title: TextView
    private lateinit var countdown: TextView

    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        AppLock(this).protectWindow()
        if (Build.VERSION.SDK_INT >= 27) { setShowWhenLocked(true); setTurnScreenOn(true) }
        else @Suppress("DEPRECATION") window.addFlags(WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED or WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        window.statusBarColor = Palette.BG; window.navigationBarColor = Palette.BG
        val column = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER_HORIZONTAL
            setPadding(dp(24), dp(56), dp(24), dp(40))
        }
        title = heading("Ringing to find your phone").apply { gravity = Gravity.CENTER }
        countdown = text("", UiType.BODY, Palette.MUTED).apply { gravity = Gravity.CENTER; setPadding(0, dp(12), 0, 0) }
        column.addView(title, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        column.addView(countdown, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        // One very large target: found it, stop it.
        column.addView(FrameLayout(this).apply {
            addView(button("Stop", true) { stopRing() }.apply {
                textSize = 32f; minHeight = 0; minimumHeight = 0
                background = gradientFill(999); contentDescription = "Stop ringing"
            }, FrameLayout.LayoutParams(dp(220), dp(220), Gravity.CENTER))
        }, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
        column.addView(text("A volume key or the power button also stops it.", UiType.META, Palette.MUTED).apply { gravity = Gravity.CENTER },
            LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        setContentView(FrameLayout(this).apply { addView(StringField(context)); addView(column) })
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() = stopRing()
        })
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                launch { OrionRing.state.collect { show(it) } }
                launch { while (true) { countdown.text = "Stops by itself in ${OrionRing.remaining()} s"; delay(1000) } }
            }
        }
    }

    private fun show(state: FindPhoneRing.State) {
        when (state) {
            is FindPhoneRing.State.Ringing -> title.text = state.from?.let { "Ringing to find your phone — $it" } ?: "Ringing to find your phone"
            FindPhoneRing.State.Idle -> finish()
        }
    }

    private fun stopRing() { OrionRing.stop(this); finish() }

    override fun onKeyDown(keyCode: Int, event: KeyEvent?): Boolean {
        if (keyCode == KeyEvent.KEYCODE_VOLUME_UP || keyCode == KeyEvent.KEYCODE_VOLUME_DOWN || keyCode == KeyEvent.KEYCODE_VOLUME_MUTE) {
            stopRing(); return true
        }
        return super.onKeyDown(keyCode, event)
    }

    /** Over the lock screen this stays a single screen; it never opens the rest of Saiph. */
    override fun onStop() {
        super.onStop()
        if (getSystemService(KeyguardManager::class.java).isKeyguardLocked) finish()
    }
}
