// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.graphics.Path
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.view.WindowManager
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo

/**
 * Opt-in input from the computer during a live phone screen session only. The owner turns
 * it on in Android's Accessibility settings after Saiph's explanation screen. It reads no
 * events and keeps nothing: it only taps, swipes, presses Back/Home/Recents and edits the
 * focused text field when the live [ScreenShareService] passes it a validated request.
 * Without it, the phone screen is view only.
 */
class SaiphInputService : AccessibilityService() {
    companion object {
        @Volatile private var instance: SaiphInputService? = null
        fun connected() = instance != null
        fun enabled(context: Context): Boolean {
            val names = Settings.Secure.getString(context.contentResolver, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES).orEmpty()
            val own = ComponentName(context, SaiphInputService::class.java)
            return names.split(':').any { ComponentName.unflattenFromString(it) == own }
        }
        internal fun perform(request: ScreenRequest): Boolean = instance?.run(request) ?: false
        internal fun launch(intent: Intent): Boolean = instance?.let { runCatching { it.startActivity(intent) }.isSuccess } ?: false
    }

    override fun onServiceConnected() { instance = this }
    override fun onUnbind(intent: Intent?): Boolean { instance = null; return super.onUnbind(intent) }
    override fun onDestroy() { instance = null; super.onDestroy() }
    override fun onAccessibilityEvent(event: AccessibilityEvent?) = Unit
    override fun onInterrupt() = Unit

    private fun size(): Pair<Int, Int> {
        val manager = getSystemService(WindowManager::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) manager.currentWindowMetrics.bounds.let { return it.width() to it.height() }
        val metrics = android.util.DisplayMetrics()
        @Suppress("DEPRECATION") manager.defaultDisplay.getRealMetrics(metrics)
        return metrics.widthPixels to metrics.heightPixels
    }

    private fun run(request: ScreenRequest): Boolean {
        // Input exists only inside the owner's current, visible screen session.
        if (!ScreenShareService.live()) return false
        val (width, height) = size()
        fun x(value: Int) = ScreenProtocol.pixel(value, width)
        fun y(value: Int) = ScreenProtocol.pixel(value, height)
        return when (request) {
            is ScreenRequest.Tap -> stroke(Path().apply { moveTo(x(request.x), y(request.y)) }, if (request.long) 650 else 60)
            is ScreenRequest.Swipe -> stroke(Path().apply { moveTo(x(request.x), y(request.y)); lineTo(x(request.x2), y(request.y2)) }, request.ms.toLong())
            is ScreenRequest.Key -> when (request.key) {
                "back" -> performGlobalAction(GLOBAL_ACTION_BACK)
                "home" -> performGlobalAction(GLOBAL_ACTION_HOME)
                "recents" -> performGlobalAction(GLOBAL_ACTION_RECENTS)
                "backspace" -> edit(null)
                "enter" -> enter()
                else -> false
            }
            is ScreenRequest.Text -> edit(request.text)
            else -> false
        }
    }

    private fun stroke(path: Path, duration: Long) =
        dispatchGesture(GestureDescription.Builder().addStroke(GestureDescription.StrokeDescription(path, 0, duration)).build(), null, null)

    private fun focused(): AccessibilityNodeInfo? = findFocus(AccessibilityNodeInfo.FOCUS_INPUT)?.takeIf { it.isEditable }

    private fun edit(typed: String?): Boolean {
        val node = focused() ?: return false
        val current = if (node.isShowingHintText) "" else node.text?.toString().orEmpty()
        val (text, cursor) = ScreenProtocol.edit(current, node.textSelectionStart, node.textSelectionEnd, typed)
        val set = node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT,
            Bundle().apply { putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text) })
        node.performAction(AccessibilityNodeInfo.ACTION_SET_SELECTION, Bundle().apply {
            putInt(AccessibilityNodeInfo.ACTION_ARGUMENT_SELECTION_START_INT, cursor)
            putInt(AccessibilityNodeInfo.ACTION_ARGUMENT_SELECTION_END_INT, cursor)
        })
        return set
    }

    private fun enter(): Boolean {
        val node = focused() ?: return false
        return Build.VERSION.SDK_INT >= Build.VERSION_CODES.R &&
            node.performAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_IME_ENTER.id)
    }
}
