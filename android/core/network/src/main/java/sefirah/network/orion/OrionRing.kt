// SPDX-License-Identifier: GPL-3.0-only
package sefirah.network.orion

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.media.AudioAttributes
import android.media.Ringtone
import android.media.RingtoneManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import androidx.core.app.NotificationCompat
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

/**
 * "Find phone" from a paired computer: alarm sound for up to 30 seconds. While it rings,
 * a full-screen Stop screen opens (over the lock screen too) and an ongoing notification
 * keeps Stop one tap away; swiping that notification away brings it back. Stop on the
 * screen, the notification, a volume key or a power press stops it everywhere.
 */
object OrionRing {
    private const val CHANNEL = "orion_ring"
    private const val NOTIFICATION = 43
    const val SECONDS = 30L
    /** The app's full-screen Stop screen; core code names it rather than linking to the app module. */
    private const val SCREEN = "com.orionmini.mobile.FindPhoneActivity"
    internal const val ACTION_STOP = "sefirah.network.orion.RING_STOP"
    internal const val ACTION_DISMISSED = "sefirah.network.orion.RING_DISMISSED"
    private val handler = Handler(Looper.getMainLooper())
    private val ring = FindPhoneRing()
    private val current = MutableStateFlow<FindPhoneRing.State>(FindPhoneRing.State.Idle)
    /** Idle or ringing; the Stop screen closes itself when this returns to idle. */
    val state: StateFlow<FindPhoneRing.State> = current
    private var ringtone: Ringtone? = null
    private var stopLater: Runnable? = null
    private var screenOff: BroadcastReceiver? = null

    /** [from] is the asking computer's display name when the transport knows it. */
    fun start(context: Context, from: String? = null) = handler.post {
        val app = context.applicationContext
        silence(app, idle = false) // A repeat request restarts the ring; it never reports "stopped" in between.
        val ringing = ring.start(from, System.currentTimeMillis())
        current.value = ringing
        val uri = RingtoneManager.getActualDefaultRingtoneUri(app, RingtoneManager.TYPE_ALARM)
            ?: RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE)
        ringtone = RingtoneManager.getRingtone(app, uri)?.apply {
            // Alarm usage plays at alarm volume, which silent mode does not mute.
            audioAttributes = AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ALARM)
                .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build()
            if (Build.VERSION.SDK_INT >= 28) isLooping = true
            play()
        }
        notify(app, ringing)
        // A power press stops it, like an alarm. Registered only while ringing.
        screenOff = object : BroadcastReceiver() {
            override fun onReceive(context: Context, intent: Intent) { stop(context) }
        }.also { runCatching { androidx.core.content.ContextCompat.registerReceiver(app, it, IntentFilter(Intent.ACTION_SCREEN_OFF), androidx.core.content.ContextCompat.RECEIVER_NOT_EXPORTED) } }
        // Open the Stop screen now when Saiph is in front; otherwise the full-screen notification does.
        runCatching { app.startActivity(screen(app).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)) }
        stopLater = Runnable { if (ring.expire(System.currentTimeMillis())) silence(app) }.also { handler.postDelayed(it, SECONDS * 1000) }
    }

    fun stop(context: Context) = handler.post { if (ring.stop()) silence(context.applicationContext) }

    /** The notification was swiped away: show it again while still ringing. */
    internal fun dismissed(context: Context) = handler.post {
        val app = context.applicationContext
        val ringing = ring.state as? FindPhoneRing.State.Ringing
        if (ring.dismissed(System.currentTimeMillis()) && ringing != null) notify(app, ringing) else if (ringing != null) silence(app)
    }

    /** Whole seconds left; 0 when not ringing. */
    fun remaining(): Long = ring.remaining(System.currentTimeMillis())

    private fun screen(context: Context) = Intent().setClassName(context.packageName, SCREEN)

    private fun notify(app: Context, ringing: FindPhoneRing.State.Ringing) {
        val manager = app.getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= 26) manager.createNotificationChannel(NotificationChannel(CHANNEL, "Ring my phone", NotificationManager.IMPORTANCE_HIGH))
        fun broadcast(action: String, code: Int) = PendingIntent.getBroadcast(app, code, Intent(app, OrionRingReceiver::class.java).setAction(action),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val stop = broadcast(ACTION_STOP, NOTIFICATION)
        val open = PendingIntent.getActivity(app, NOTIFICATION, screen(app).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        runCatching {
            manager.notify(NOTIFICATION, NotificationCompat.Builder(app, CHANNEL).setSmallIcon(android.R.drawable.ic_lock_silent_mode_off)
                .setContentTitle("Ringing to find your phone").setContentText(ringing.from?.let { "Asked by $it. Tap Stop." } ?: "Tap Stop.")
                .setOngoing(true).setOnlyAlertOnce(true).setAutoCancel(false)
                .setContentIntent(open).setFullScreenIntent(open, true)
                .setDeleteIntent(broadcast(ACTION_DISMISSED, NOTIFICATION + 1)).addAction(0, "Stop", stop)
                .setTimeoutAfter(SECONDS * 1000 + 1000)
                .setPriority(NotificationCompat.PRIORITY_MAX).setCategory(NotificationCompat.CATEGORY_ALARM).build())
        }
    }

    /** Sound, notification, power-press listener and timer off; the Stop screen and computers learn from [state]. */
    private fun silence(app: Context, idle: Boolean = true) {
        stopLater?.let(handler::removeCallbacks); stopLater = null
        ringtone?.stop(); ringtone = null
        screenOff?.let { runCatching { app.unregisterReceiver(it) } }; screenOff = null
        app.getSystemService(NotificationManager::class.java).cancel(NOTIFICATION)
        if (idle) current.value = FindPhoneRing.State.Idle
    }
}

class OrionRingReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        // The notification's delete intent brings it back; anything else (Stop, older notifications) stops.
        if (intent.action == OrionRing.ACTION_DISMISSED) OrionRing.dismissed(context) else OrionRing.stop(context)
    }
}
