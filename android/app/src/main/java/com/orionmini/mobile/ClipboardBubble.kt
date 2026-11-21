// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.annotation.SuppressLint
import android.content.Context
import android.content.Intent
import android.content.res.ColorStateList
import android.graphics.PixelFormat
import android.net.Uri
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import android.view.WindowManager
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.Toast
import sefirah.clipboard.ClipboardChangeActivity
import sefirah.clipboard.ClipboardSend
import kotlin.math.abs

/**
 * The clipboard bubble: a small Saiph button over other apps. Copy something, tap the bubble,
 * and it goes to your computer without opening Saiph.
 *
 * Android lets an app read the clipboard only while one of its windows has focus, so a tap opens
 * [ClipboardChangeActivity] for a moment, which reads and sends. Drawing over other apps needs
 * Android's "Display over other apps" access; the owner turns the bubble on in Settings → Clipboard.
 * Drag moves it, and it settles against the nearer screen edge; a long press hides it.
 */
object ClipboardBubble {
    private const val KEY = "clipboard_bubble"
    private const val ASKED = "clipboard_bubble_offered"
    private val main = Handler(Looper.getMainLooper())
    private var bubble: View? = null

    private fun prefs(context: Context) = context.getSharedPreferences("orion", 0)
    fun enabled(context: Context) = prefs(context).getBoolean(KEY, false)
    fun allowed(context: Context) = Settings.canDrawOverlays(context)
    /** A phone paired with a Hub or approved on a Saiph account. */
    private fun connected(context: Context) = prefs(context).contains("device_id") ||
        context.getSharedPreferences("orion_hosted", 0).contains("device_id")

    /** Android's page for "Display over other apps", opened on Saiph's own entry. */
    fun overlaySettings(context: Context) = Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:" + context.packageName))

    fun setEnabled(context: Context, on: Boolean) {
        prefs(context).edit().putBoolean(KEY, on).apply()
        sync(context)
    }

    /** Shows or removes the bubble to match its switch, Android's access and clipboard sharing. Safe to call often. */
    fun sync(context: Context) {
        val app = context.applicationContext
        main.post {
            val wanted = enabled(app) && allowed(app) && connected(app) && prefs(app).getBoolean("clipboard_enabled", true)
            if (wanted && bubble == null) show(app) else if (!wanted) hide(app)
        }
    }

    /** Sends the clipboard now and says what happened; the home screen's Clipboard action uses it too. */
    fun sendNow(context: Context, answered: (ClipboardSend) -> Unit = {}) {
        val app = context.applicationContext
        ClipboardChangeActivity.launch(app) { result ->
            main.post {
                Toast.makeText(app, when (result) {
                    ClipboardSend.SENT -> "Clipboard sent to your computer"
                    ClipboardSend.EMPTY -> "Nothing copied yet"
                    ClipboardSend.NOT_SENT -> "Not sent. Check that Saiph is online and clipboard sharing is on."
                }, Toast.LENGTH_SHORT).show()
                answered(result)
            }
        }
    }

    /** After the first send from inside Saiph, offer the bubble once, so sending works from any app. */
    fun shouldOffer(context: Context) = !enabled(context) && !prefs(context).getBoolean(ASKED, false)
    fun offered(context: Context) = prefs(context).edit().putBoolean(ASKED, true).apply()

    private fun hide(context: Context) {
        val view = bubble ?: return
        bubble = null
        runCatching { context.getSystemService(WindowManager::class.java).removeView(view) }
    }

    @SuppressLint("ClickableViewAccessibility")
    private fun show(context: Context) {
        val windows = context.getSystemService(WindowManager::class.java)
        val size = context.dp(56)
        val metrics = context.resources.displayMetrics
        val params = WindowManager.LayoutParams(size, size, WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS, PixelFormat.TRANSLUCENT).apply {
            gravity = Gravity.TOP or Gravity.START
            x = prefs(context).getInt("clipboard_bubble_x", metrics.widthPixels - size - context.dp(8))
            y = prefs(context).getInt("clipboard_bubble_y", metrics.heightPixels / 3)
        }
        val icon = ImageView(context).apply {
            setImageResource(sefirah.common.R.drawable.ic_content_paste)
            imageTintList = ColorStateList.valueOf(Palette.ON_ACCENT)
            setPadding(context.dp(14), context.dp(14), context.dp(14), context.dp(14))
        }
        val view = FrameLayout(context).apply {
            background = context.outline(Palette.ACCENT, 0xFFFFFFFF.toInt(), 999).apply { setStroke(context.dp(2), 0xFFFFFFFF.toInt()) }
            elevation = context.dp(6).toFloat()
            contentDescription = "Send clipboard to your computer"
            addView(icon, FrameLayout.LayoutParams(size, size))
        }
        val slop = ViewConfiguration.get(context).scaledTouchSlop
        var startX = 0; var startY = 0; var downX = 0f; var downY = 0f; var dragging = false; var pressed = 0L
        val longPress = Runnable {
            if (dragging) return@Runnable
            setEnabled(context, false)
            Toast.makeText(context, "Clipboard bubble hidden. Turn it back on in Saiph → Settings → Clipboard.", Toast.LENGTH_LONG).show()
        }
        view.setOnTouchListener { _, event ->
            when (event.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    startX = params.x; startY = params.y; downX = event.rawX; downY = event.rawY; dragging = false; pressed = event.eventTime
                    main.postDelayed(longPress, ViewConfiguration.getLongPressTimeout().toLong() + 300)
                }
                MotionEvent.ACTION_MOVE -> {
                    val dx = event.rawX - downX; val dy = event.rawY - downY
                    if (!dragging && (abs(dx) > slop || abs(dy) > slop)) { dragging = true; main.removeCallbacks(longPress) }
                    if (dragging) {
                        params.x = startX + dx.toInt(); params.y = (startY + dy.toInt()).coerceIn(0, metrics.heightPixels - size)
                        runCatching { windows.updateViewLayout(view, params) }
                    }
                }
                MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                    main.removeCallbacks(longPress)
                    if (dragging) {
                        // Settle against the nearer edge, so the bubble never covers the middle of an app.
                        params.x = if (params.x + size / 2 < metrics.widthPixels / 2) context.dp(8) else metrics.widthPixels - size - context.dp(8)
                        runCatching { windows.updateViewLayout(view, params) }
                        prefs(context).edit().putInt("clipboard_bubble_x", params.x).putInt("clipboard_bubble_y", params.y).apply()
                    } else if (event.actionMasked == MotionEvent.ACTION_UP && event.eventTime - pressed < ViewConfiguration.getLongPressTimeout()) {
                        view.performClick()
                        sendNow(context) { result ->
                            // A tick for a moment when it went; the clipboard icon again after.
                            if (result == ClipboardSend.SENT) {
                                icon.setImageResource(sefirah.common.R.drawable.ic_check)
                                main.postDelayed({ icon.setImageResource(sefirah.common.R.drawable.ic_content_paste) }, 1500)
                            }
                        }
                    }
                }
            }
            true
        }
        runCatching { windows.addView(view, params); bubble = view }
    }
}

/** Whether the optional accessibility service that sends every copy is on. */
fun Context.clipboardAutoOn(): Boolean {
    val service = packageName + "/" + sefirah.clipboard.ClipboardAccessibilityService::class.java.name
    return Settings.Secure.getString(contentResolver, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES).orEmpty()
        .split(':').any { it.equals(service, ignoreCase = true) }
}

/**
 * Settings → Clipboard, the same on Cloud and Hub phones: the bubble, then automatic sending.
 * [open] opens one of Android's settings pages; the page redraws on return.
 */
fun SettingsPage.clipboardControls(context: Context, open: (Intent) -> Unit, redraw: () -> Unit) {
    val on = ClipboardBubble.enabled(context)
    val allowed = ClipboardBubble.allowed(context)
    switchItem("clipboard_bubble", "A small button over other apps. Copy something, tap it, and it goes to your computer. Drag it to move; press and hold to hide it.",
        on && allowed, build = {
            if (on && !allowed) {
                addView(context.text("Allow \"Display over other apps\" for Saiph to show the bubble.", UiType.META, Palette.WARN).apply { setPadding(0, context.dp(4), 0, 0) })
                addView(context.compactActions(context.compactButton("Allow") { open(ClipboardBubble.overlaySettings(context)) }))
            }
        }) { _, checked ->
        ClipboardBubble.setEnabled(context, checked)
        if (checked && !ClipboardBubble.allowed(context)) open(ClipboardBubble.overlaySettings(context)) else redraw()
    }
    if (com.castle.sefirah.BuildConfig.PLAY_STORE) return
    linkItem("clipboard_auto", if (context.clipboardAutoOn()) "On. Each copy goes to your computer without a tap."
        else "Off. Turn on Saiph in Accessibility to send each copy without a tap.",
        external = true) { open(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)) }
}
