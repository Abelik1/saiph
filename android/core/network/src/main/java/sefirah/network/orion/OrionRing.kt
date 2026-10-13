// SPDX-License-Identifier: GPL-3.0-only
package sefirah.network.orion

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.media.AudioAttributes
import android.media.Ringtone
import android.media.RingtoneManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import androidx.core.app.NotificationCompat

/** "Ring my phone" from a paired computer: alarm sound for up to 30 seconds, with Stop. */
object OrionRing {
    private const val CHANNEL = "orion_ring"
    private const val NOTIFICATION = 43
    const val SECONDS = 30L
    private val handler = Handler(Looper.getMainLooper())
    private var ringtone: Ringtone? = null
    private var stopLater: Runnable? = null

    fun start(context: Context) = handler.post {
        val app = context.applicationContext
        stopNow(app)
        val uri = RingtoneManager.getActualDefaultRingtoneUri(app, RingtoneManager.TYPE_ALARM)
            ?: RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE)
        ringtone = RingtoneManager.getRingtone(app, uri)?.apply {
            // Alarm usage plays at alarm volume, which silent mode does not mute.
            audioAttributes = AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ALARM)
                .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build()
            if (Build.VERSION.SDK_INT >= 28) isLooping = true
            play()
        }
        val manager = app.getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= 26) manager.createNotificationChannel(NotificationChannel(CHANNEL, "Ring my phone", NotificationManager.IMPORTANCE_HIGH))
        val stop = PendingIntent.getBroadcast(app, NOTIFICATION, Intent(app, OrionRingReceiver::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        runCatching {
            manager.notify(NOTIFICATION, NotificationCompat.Builder(app, CHANNEL).setSmallIcon(android.R.drawable.ic_lock_silent_mode_off)
                .setContentTitle("Your computer is ringing this phone").setContentText("Tap to stop.")
                .setContentIntent(stop).setDeleteIntent(stop).addAction(0, "Stop", stop)
                .setPriority(NotificationCompat.PRIORITY_HIGH).setCategory(NotificationCompat.CATEGORY_ALARM).build())
        }
        stopLater = Runnable { stopNow(app) }.also { handler.postDelayed(it, SECONDS * 1000) }
    }

    fun stop(context: Context) = handler.post { stopNow(context.applicationContext) }

    private fun stopNow(context: Context) {
        stopLater?.let(handler::removeCallbacks); stopLater = null
        ringtone?.stop(); ringtone = null
        context.getSystemService(NotificationManager::class.java).cancel(NOTIFICATION)
    }
}

class OrionRingReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) { OrionRing.stop(context) }
}
