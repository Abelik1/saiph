// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat

/**
 * "Start camera for <computer>?" for a session offer from an approved computer.
 * The notification and its intent carry only the offer ID; the invitation stays
 * in [SessionOffers]. Local-only, so it is never mirrored to a computer.
 */
internal object CameraRequests {
    const val EXTRA_OFFER = "session_offer"
    private const val CHANNEL = "orion_camera_requests"
    private const val NOTIFICATION = 46

    fun show(context: Context, offer: SessionOffer, computer: String, now: Long = System.currentTimeMillis() / 1000) {
        val manager = context.getSystemService(NotificationManager::class.java) ?: return
        manager.createNotificationChannel(NotificationChannel(CHANNEL, "Camera requests", NotificationManager.IMPORTANCE_HIGH))
        val open = PendingIntent.getActivity(context, NOTIFICATION,
            Intent(context, PhoneCameraActivity::class.java).putExtra(EXTRA_OFFER, offer.id).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val title = RequestBoard.copy("camera", computer).first
        val body = "Tap to open Saiph. You confirm with your screen lock before the camera starts."
        val allow = PendingIntent.getActivity(context, NOTIFICATION + 1, RequestPrompts.allowIntent(context, "camera", offer.id),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        runCatching {
            manager.notify(NOTIFICATION, NotificationCompat.Builder(context, CHANNEL).setSmallIcon(android.R.drawable.ic_menu_camera)
                .setContentTitle(title).setContentText(body).setStyle(NotificationCompat.BigTextStyle().bigText(body))
                .setContentIntent(open).addAction(0, "Allow", allow).setAutoCancel(true).setLocalOnly(true).setOnlyAlertOnce(true)
                .setTimeoutAfter(((offer.expiresAt - now) * 1000).coerceIn(1000, SessionOffer.MAX_LIFETIME * 1000))
                .setPriority(NotificationCompat.PRIORITY_HIGH).setCategory(NotificationCompat.CATEGORY_RECOMMENDATION).build())
        }
    }

    fun dismiss(context: Context) { runCatching { context.getSystemService(NotificationManager::class.java)?.cancel(NOTIFICATION) } }
}
