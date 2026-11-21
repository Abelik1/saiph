// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.content.Context
import android.content.res.ColorStateList
import android.graphics.drawable.RippleDrawable
import android.text.TextUtils
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout

/**
 * The home screen is a remote: big tiles for what people start, a row of smaller actions,
 * then their devices. Settings stay behind the gear (docs/MOBILE_DESIGN_SYSTEM.md, "Home").
 */
data class RemoteTile(val icon: Int, val label: String, val badge: String? = null, val run: () -> Unit)

/** Big tiles, two to a row. An odd last tile keeps its half width. */
fun Context.remoteTiles(vararg tiles: RemoteTile): LinearLayout = LinearLayout(this).apply {
    orientation = LinearLayout.VERTICAL
    tiles.toList().chunked(2).forEachIndexed { index, pair ->
        addView(LinearLayout(context).apply {
            orientation = LinearLayout.HORIZONTAL
            pair.forEachIndexed { column, tile ->
                addView(remoteTile(tile), LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply { if (column > 0) marginStart = dp(12) })
            }
            if (pair.size == 1) addView(View(context), LinearLayout.LayoutParams(0, 0, 1f).apply { marginStart = dp(12) })
        }, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { if (index > 0) topMargin = dp(12) })
    }
}

private fun Context.remoteTile(tile: RemoteTile): View = FrameLayout(this).apply {
    background = RippleDrawable(ColorStateList.valueOf(0x33FFFFFF), outline(0xE60A1224.toInt(), Palette.LINE_STRONG, 22), null)
    isClickable = true; isFocusable = true
    contentDescription = tile.label + (tile.badge?.let { ", $it" } ?: "")
    minimumHeight = dp(140)
    setPadding(dp(12), dp(16), dp(12), dp(16))
    // Icon over label, both centred in the tile.
    addView(LinearLayout(context).apply {
        orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER_HORIZONTAL
        addView(ImageView(context).apply {
            setImageResource(tile.icon); imageTintList = ColorStateList.valueOf(Palette.ON_TONAL)
            background = outline(Palette.TONAL, Palette.TONAL_LINE, 18); setPadding(dp(13), dp(13), dp(13), dp(13))
            importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
        }, LinearLayout.LayoutParams(dp(56), dp(56)))
        // The label wraps to two lines, so "Use as webcam" never truncates.
        addView(text(tile.label, UiType.TITLE, bold = true).apply {
            gravity = Gravity.CENTER; maxLines = 2; ellipsize = TextUtils.TruncateAt.END
            importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
        }, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { topMargin = dp(14) })
    }, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.CENTER))
    tile.badge?.let { label ->
        addView(text(label, 12f, Palette.ON_ACCENT, bold = true).apply {
            background = outline(Palette.ACCENT, Palette.ACCENT, 999); setPadding(dp(8), dp(3), dp(8), dp(3))
            importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
        }, FrameLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.TOP or Gravity.END))
    }
    setOnClickListener { tile.run() }
}

/** Smaller actions under the tiles: a round icon over a short label, spread across one row. */
fun Context.miniActions(vararg actions: QuickAction): LinearLayout = LinearLayout(this).apply {
    orientation = LinearLayout.HORIZONTAL; gravity = Gravity.START
    setPadding(0, dp(18), 0, dp(4))
    actions.forEach { action ->
        addView(LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER_HORIZONTAL
            contentDescription = action.label; isClickable = true; isFocusable = true
            background = RippleDrawable(ColorStateList.valueOf(0x33FFFFFF), outline(0, 0, 16), null)
            setPadding(dp(2), dp(4), dp(2), dp(4))
            addView(ImageView(context).apply {
                setImageResource(action.icon); imageTintList = ColorStateList.valueOf(Palette.TEXT)
                background = outline(Palette.MUTED_FILL, Palette.LINE_STRONG, 999); setPadding(dp(13), dp(13), dp(13), dp(13))
                importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
            }, LinearLayout.LayoutParams(dp(50), dp(50)))
            addView(text(action.label, 13f, Palette.MUTED).apply {
                gravity = Gravity.CENTER; maxLines = 1; ellipsize = TextUtils.TruncateAt.END; setPadding(0, dp(6), 0, 0)
                importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
            })
            setOnClickListener { action.run() }
        // Five fit across a phone; fewer keep the same size instead of stretching.
        }, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
    }
    weightSum = maxOf(actions.size, 5).toFloat()
}

/** Shown only while something waits for the owner: an amber dot, one line, and Review. */
fun Context.needsYou(message: String, run: () -> Unit): View = LinearLayout(this).apply {
    orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
    background = RippleDrawable(ColorStateList.valueOf(0x33FFFFFF), outline(Palette.DUE_SURFACE, 0x66F7B645, 14), null)
    isClickable = true; isFocusable = true; contentDescription = "$message. Review"
    setPadding(dp(14), dp(12), dp(14), dp(12))
    addView(View(context).apply { background = outline(Palette.DUE, Palette.DUE, 999) }, LinearLayout.LayoutParams(dp(8), dp(8)).apply { marginEnd = dp(10) })
    addView(text(message, UiType.META).apply { maxLines = 2; ellipsize = TextUtils.TruncateAt.END; importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO },
        LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
    addView(text("Review", UiType.META, Palette.DUE, bold = true).apply { importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO },
        LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { marginStart = dp(10) })
    layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { bottomMargin = dp(14) }
    setOnClickListener { run() }
}

/** A device row's action: a small tonal pill with an icon, such as Ring, Lock or Wake. */
fun Context.deviceAction(icon: Int, label: String, run: () -> Unit) = compactButton(label) { run() }.apply {
    val glyph = androidx.core.content.ContextCompat.getDrawable(context, icon)?.mutate()?.apply { setBounds(0, 0, dp(18), dp(18)) }
    setCompoundDrawablesRelative(glyph, null, null, null)
    androidx.core.widget.TextViewCompat.setCompoundDrawableTintList(this, ColorStateList.valueOf(Palette.ON_TONAL))
    compoundDrawablePadding = dp(6); textSize = UiType.META
    minHeight = dp(40); minimumHeight = dp(40); setPadding(dp(12), dp(6), dp(14), dp(6))
}

/** Android lets only system apps switch the hotspot on; open its settings page instead. */
fun Context.hotspotSettings() {
    val tethering = android.content.Intent(android.content.Intent.ACTION_MAIN).setClassName("com.android.settings", "com.android.settings.TetherSettings")
    try { startActivity(tethering) } catch (_: Exception) {
        runCatching { startActivity(android.content.Intent(android.provider.Settings.ACTION_WIRELESS_SETTINGS)) }
    }
}

/** The actions under the home screen's tiles, the same on Cloud and Hub phones. */
fun Context.homeActions(clipboard: () -> Unit) = miniActions(
    QuickAction(sefirah.common.R.drawable.ic_content_paste, "Clipboard", clipboard),
    QuickAction(com.castle.sefirah.R.drawable.saiph_ic_photo, "Photo") { startActivity(android.content.Intent(this, OrionCaptureActivity::class.java)) },
    QuickAction(com.castle.sefirah.R.drawable.saiph_ic_sketch, "Sketch") { startActivity(android.content.Intent(this, OrionSketchActivity::class.java)) },
    QuickAction(com.castle.sefirah.R.drawable.saiph_ic_remote, "Remote") { startActivity(android.content.Intent(this, OrionRemoteActivity::class.java)) },
    QuickAction(com.castle.sefirah.R.drawable.saiph_ic_hotspot, "Hotspot") { hotspotSettings() })

/** "Your devices": one row per computer with its icon, name and status, then its actions on the right. */
fun Context.deviceRow(icon: Int, name: String, detail: String, vararg actions: android.widget.Button) = LinearLayout(this).apply {
    orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL; setPadding(0, dp(8), 0, dp(8))
    addView(ImageView(context).apply { setImageResource(icon); imageTintList = ColorStateList.valueOf(Palette.MUTED); importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO },
        LinearLayout.LayoutParams(dp(24), dp(24)).apply { marginEnd = dp(12) })
    addView(LinearLayout(context).apply {
        orientation = LinearLayout.VERTICAL
        addView(text(name, UiType.BODY).apply { maxLines = 1; ellipsize = TextUtils.TruncateAt.END })
        addView(text(detail, 13f, Palette.MUTED))
    }, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
    actions.forEach { addView(it, LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { marginStart = dp(6) }) }
}

/** The "Your devices" heading and its card; rows are added by the caller, divided by hairlines. */
fun Context.devicesCard(root: LinearLayout): LinearLayout {
    root.addView(eyebrow("Your devices").apply { setPadding(dp(4), dp(22), 0, dp(8)) })
    return card().apply { setPadding(dp(14), dp(6), dp(14), dp(6)) }.also { root.addView(it) }
}

fun LinearLayout.addDeviceRow(row: View) {
    if (childCount > 0) addView(context.divider().apply { (layoutParams as LinearLayout.LayoutParams).setMargins(0, 0, 0, 0) })
    addView(row)
}

/**
 * A whole-page message with a large icon, used when a page has nothing to show yet (no computer
 * offers it, or Saiph is reconnecting): one title, one line on what to do, then its actions.
 */
fun Context.emptyState(icon: Int, title: String, detail: String, vararg actions: android.widget.Button): LinearLayout = LinearLayout(this).apply {
    orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER_HORIZONTAL
    setPadding(dp(8), dp(40), dp(8), dp(24))
    addView(ImageView(context).apply {
        setImageResource(icon); imageTintList = ColorStateList.valueOf(Palette.ON_TONAL)
        background = outline(Palette.TONAL, Palette.TONAL_LINE, 32); setPadding(dp(26), dp(26), dp(26), dp(26))
        importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
    }, LinearLayout.LayoutParams(dp(104), dp(104)))
    addView(text(title, UiType.TITLE, bold = true).apply {
        gravity = Gravity.CENTER; androidx.core.view.ViewCompat.setAccessibilityHeading(this, true)
    }, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { topMargin = dp(22) })
    addView(text(detail, UiType.BODY, Palette.MUTED).apply { gravity = Gravity.CENTER },
        LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { topMargin = dp(8) })
    actions.forEach { addView(it, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { topMargin = dp(20) }) }
}
