// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat
import com.castle.sefirah.R

/**
 * A computer's phone screen offer, delivered over Saiph Cloud, shown as a local-only
 * notification. Tapping it only opens [PhoneScreenActivity]; nothing is shared before the
 * owner verifies and accepts Android's capture prompt there.
 */
internal object ScreenOfferNotice {
    private const val CHANNEL = "orion_screen_offer"
    private const val OFFER = 7302
    private const val OPEN_APP = 7303

    private fun channel(context: Context) = context.getSystemService(NotificationManager::class.java).apply {
        createNotificationChannel(NotificationChannel(CHANNEL, "Phone screen requests", NotificationManager.IMPORTANCE_HIGH))
    }

    /** The notification carries only the offer ID; the invitation stays in [SessionOffers]. */
    fun show(context: Context, offer: SessionOffer, computer: String, now: Long = System.currentTimeMillis() / 1000) {
        if (ScreenShareService.active()) return
        val intent = Intent(context, PhoneScreenActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
            .putExtra(PhoneScreenActivity.EXTRA_OFFER, offer.id)
        val open = PendingIntent.getActivity(context, OFFER, intent, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val allow = PendingIntent.getActivity(context, OFFER + 10, RequestPrompts.allowIntent(context, "screen", offer.id)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        channel(context).notify(OFFER, NotificationCompat.Builder(context, CHANNEL).setSmallIcon(R.drawable.ic_saiph_tile)
            .setContentTitle(RequestBoard.copy("screen", computer).first)
            .setContentText("Tap to choose. Nothing is shared until you verify it's you and start.")
            .setPriority(NotificationCompat.PRIORITY_HIGH).setCategory(NotificationCompat.CATEGORY_RECOMMENDATION)
            .setLocalOnly(true).setOnlyAlertOnce(true).setAutoCancel(true)
            .setTimeoutAfter(((offer.expiresAt - now) * 1000).coerceIn(1000, SessionOffer.MAX_LIFETIME * 1000))
            .setContentIntent(open).addAction(0, "Allow", allow).build())
    }

    fun clear(context: Context) = context.getSystemService(NotificationManager::class.java).cancel(OFFER)

    /** Android blocked opening an app from the background: the owner taps to open it. */
    fun openApp(context: Context, packageName: String, launch: Intent) {
        val label = runCatching { context.packageManager.getApplicationLabel(context.packageManager.getApplicationInfo(packageName, 0)).toString() }
            .getOrDefault(packageName)
        val open = PendingIntent.getActivity(context, packageName.hashCode(), launch, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        channel(context).notify(OPEN_APP, NotificationCompat.Builder(context, CHANNEL).setSmallIcon(R.drawable.ic_saiph_tile)
            .setContentTitle("Open $label").setContentText("Your computer asked to show $label. Tap to open it.")
            .setPriority(NotificationCompat.PRIORITY_HIGH).setAutoCancel(true).setTimeoutAfter(60_000).setContentIntent(open).build())
    }
}
