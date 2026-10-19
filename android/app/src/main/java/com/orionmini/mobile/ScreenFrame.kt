// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.app.Activity
import android.os.Build
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.WindowInsets
import android.widget.Button
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ScrollView

/**
 * The frame every secondary screen shares with the main page: the strings behind, a header
 * with the Back arrow in the top corner and the screen title, the content, and an optional
 * action dock above system navigation. Back is never a "Close" button at the bottom.
 *
 * [back] runs for the header arrow; the activity's system Back must lead to the same place
 * (for a whole activity that is simply finishing it, Android's default). Pass `null` only
 * for a top-level screen, which has no in-app Back.
 *
 * With [scrolling] the content scrolls under a fixed header and dock. Without it the content
 * fills the space between them, for screens with a live preview or a canvas.
 */
class ScreenFrame(activity: Activity, title: String, back: (() -> Unit)?, scrolling: Boolean = true) {
    val header: LinearLayout
    val content: LinearLayout
    val dock: LinearLayout
    val scroll: ScrollView?

    init {
        val context = activity
        header = LinearLayout(context).apply {
            orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
            setPadding(context.dp(10), context.dp(8), context.dp(10), context.dp(8)); minimumHeight = context.dp(64)
            if (back != null) addView(context.iconButton(com.castle.sefirah.R.drawable.saiph_ic_back, "Back", back))
            addView(context.heading(title).apply {
                maxLines = 2; ellipsize = android.text.TextUtils.TruncateAt.END
                setPadding(if (back == null) context.dp(8) else context.dp(2), 0, context.dp(8), 0)
            }, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        }
        content = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL; setPadding(context.dp(18), context.dp(4), context.dp(18), context.dp(28))
        }
        scroll = if (scrolling) ScrollView(context).apply { addView(content) } else null
        dock = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL; visibility = View.GONE
            background = context.outline(Palette.BG, Palette.LINE, 0); setPadding(context.dp(18), context.dp(4), context.dp(18), context.dp(12))
        }
        val column = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            addView(header)
            addView(scroll ?: content, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
            addView(dock)
        }
        val frame = FrameLayout(context).apply { addView(StringField(context)); addView(column) }
        frame.setOnApplyWindowInsetsListener { view, insets ->
            if (Build.VERSION.SDK_INT >= 30) {
                val bars = insets.getInsets(WindowInsets.Type.systemBars()); view.setPadding(0, bars.top, 0, bars.bottom)
            } else {
                @Suppress("DEPRECATION")
                view.setPadding(0, insets.systemWindowInsetTop, 0, insets.systemWindowInsetBottom)
            }
            insets
        }
        activity.setContentView(frame)
    }

    /** The screen's main action (and at most one quieter one) where the thumb rests. */
    fun dockActions(vararg buttons: Button) {
        dock.visibility = View.VISIBLE
        dock.addView(dock.context.buttonRow(*buttons))
    }
}
