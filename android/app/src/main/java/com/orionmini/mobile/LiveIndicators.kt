// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.graphics.Typeface
import android.view.Gravity
import android.widget.LinearLayout
import android.widget.TextView
import androidx.core.app.NotificationCompat

/**
 * While the camera or the phone screen is live on a computer, Saiph says so in red: a
 * persistent banner on the camera and phone screen pages, and an ongoing notification with
 * a red accent and Stop. Photos, text and calls are not "live" and keep their usual look.
 */
internal object Live {
    const val RED = 0xFFDC2626.toInt()
    const val ON_RED = 0xFFFFFFFF.toInt()
    const val CHANNEL = "orion_live_capture"
    private const val CAMERA_NOTIFICATION = 7310
    const val EXTRA_STOP = "live_stop"

    fun channel(context: Context) {
        context.getSystemService(NotificationManager::class.java)
            ?.createNotificationChannel(NotificationChannel(CHANNEL, "Live camera and screen", NotificationManager.IMPORTANCE_LOW))
    }

    /** The phone camera's ongoing notification; the session itself lives in PhoneCameraActivity. */
    fun showCamera(context: Context, computer: String?) {
        channel(context)
        val open = Intent(context, PhoneCameraActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP)
        val stop = PendingIntent.getActivity(context, CAMERA_NOTIFICATION + 1, Intent(open).putExtra(EXTRA_STOP, true),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val show = PendingIntent.getActivity(context, CAMERA_NOTIFICATION, open, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        runCatching {
            context.getSystemService(NotificationManager::class.java)?.notify(CAMERA_NOTIFICATION,
                NotificationCompat.Builder(context, CHANNEL).setSmallIcon(android.R.drawable.ic_menu_camera)
                    .setContentTitle("● Live · Camera on" + (computer?.let { " for $it" } ?: ""))
                    .setContentText("Your computer is receiving this phone's camera. Audio is off.")
                    .setColor(RED).setColorized(true).setOngoing(true).setOnlyAlertOnce(true).setLocalOnly(true)
                    .setUsesChronometer(true).setWhen(System.currentTimeMillis())
                    .setCategory(NotificationCompat.CATEGORY_SERVICE).setContentIntent(show).addAction(0, "Stop", stop).build())
        }
    }

    fun clearCamera(context: Context) {
        runCatching { context.getSystemService(NotificationManager::class.java)?.cancel(CAMERA_NOTIFICATION) }
    }
}

/** The red banner at the top of a live camera or phone screen page. */
internal fun Context.liveBanner(message: String): LinearLayout = LinearLayout(this).apply {
    orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
    setPadding(dp(14), dp(10), dp(14), dp(10))
    background = outline(Live.RED, Live.RED, 14)
    contentDescription = message
    addView(TextView(context).apply {
        text = "● LIVE"; setTextColor(Live.ON_RED); textSize = 13f; typeface = Typeface.DEFAULT_BOLD; letterSpacing = 0.06f
        setPadding(0, 0, dp(10), 0)
    })
    addView(TextView(context).apply { text = message; setTextColor(Live.ON_RED); textSize = 14f },
        LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
    layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply { bottomMargin = dp(12) }
}
