// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.app.KeyguardManager
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.ServiceInfo
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.os.SystemClock
import android.provider.Settings
import android.view.WindowManager
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import com.castle.sefirah.R
import java.io.ByteArrayOutputStream

/**
 * One visible phone screen session for the computer that offered it. Starts only from
 * [PhoneScreenActivity] after owner verification and Android's own capture consent; shows a
 * persistent notification with Stop. Android's MediaProjection keeps FLAG_SECURE content
 * (Saiph itself, banking and password screens) black. Nothing is recorded: only the latest
 * JPEG exists, in memory. No audio. Stop, disconnect, screen off or lock end the session.
 */
class ScreenShareService : Service() {
    companion object {
        private const val ACTION_START = "com.orionmini.mobile.screen.START"
        private const val ACTION_STOP = "com.orionmini.mobile.screen.STOP"
        private const val EXTRA_RESULT = "result"
        private const val EXTRA_DATA = "data"
        private const val CHANNEL = "orion_screen_share"
        private const val NOTIFICATION = 7301
        @Volatile private var current: ScreenShareService? = null
        /** True only while a session is connected; input is refused at any other time. */
        fun live() = current?.connected == true
        fun active() = current != null

        /** The invitation is handed over in memory, never in the service intent. */
        @Volatile private var handoff: String? = null
        fun start(context: Context, invite: String, result: Int, data: Intent) {
            handoff = invite
            context.startForegroundService(Intent(context, ScreenShareService::class.java).setAction(ACTION_START)
                .putExtra(EXTRA_RESULT, result).putExtra(EXTRA_DATA, data))
        }
        fun stop(context: Context) { context.startService(Intent(context, ScreenShareService::class.java).setAction(ACTION_STOP)) }
    }

    private val thread = HandlerThread("orion-screen").apply { start() }
    private val handler = Handler(thread.looper)
    private var projection: MediaProjection? = null
    private var display: VirtualDisplay? = null
    private var reader: ImageReader? = null
    private var sender: ScreenSender? = null
    private var offer: ScreenOffer? = null
    private var cadence: CameraCadence? = null
    private var size = 0 to 0
    private var last: Triple<ByteArray, Int, Int>? = null
    private var lastSent = 0L
    private var input: Boolean? = null
    private var launched = false
    private val output = ByteArrayOutputStream(256 * 1024)
    @Volatile private var connected = false
    private val startedAt = System.currentTimeMillis()
    @Volatile private var ended = false

    private val screenOff = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) { if (intent.action == Intent.ACTION_SCREEN_OFF) end() }
    }
    private val callback = object : MediaProjection.Callback() {
        override fun onStop() { end() }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) { end(); return START_NOT_STICKY }
        val code = handoff.also { handoff = null }
        val parsed = code?.let { runCatching { ScreenOffer.parse(it) }.getOrNull() }
        @Suppress("DEPRECATION") val data = intent?.getParcelableExtra<Intent>(EXTRA_DATA)
        val result = intent?.getIntExtra(EXTRA_RESULT, 0) ?: 0
        // Android requires the visible foreground notification before the projection exists.
        val type = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION else 0
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) startForeground(NOTIFICATION, notification(false), type)
        else startForeground(NOTIFICATION, notification(false))
        if (current != null && current !== this || parsed == null || data == null || ended) { end(); return START_NOT_STICKY }
        current = this
        offer = parsed
        RequestPrompts.taken(this, "screen")  // Started by any route: no request prompt may remain.
        cadence = CameraCadence(parsed.fps)
        val manager = getSystemService(MediaProjectionManager::class.java)
        val granted = runCatching { manager.getMediaProjection(result, data) }.getOrNull()
        if (granted == null) { end(); return START_NOT_STICKY }
        projection = granted
        granted.registerCallback(callback, handler)
        ContextCompat.registerReceiver(this, screenOff, IntentFilter(Intent.ACTION_SCREEN_OFF), ContextCompat.RECEIVER_NOT_EXPORTED)
        sender = ScreenSender(parsed, connected = { handler.post(::capture) }, request = { value -> handler.post { request(value) } },
            ended = { handler.post { end() } }).also { it.connect() }
        return START_NOT_STICKY
    }

    private fun realSize(): Pair<Int, Int> {
        val manager = getSystemService(WindowManager::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) manager.currentWindowMetrics.bounds.let { return it.width() to it.height() }
        val metrics = android.util.DisplayMetrics()
        @Suppress("DEPRECATION") manager.defaultDisplay.getRealMetrics(metrics)
        return metrics.widthPixels to metrics.heightPixels
    }

    /** Starts after the computer accepted the connection; one virtual display per consent. */
    private fun capture() {
        val profile = offer ?: return
        val granted = projection ?: return
        if (ended || display != null) return
        connected = true
        val (width, height) = realSize()
        size = ScreenProtocol.captureSize(width, height, profile.maxSide, profile.maxPixels)
        val surface = ImageReader.newInstance(size.first, size.second, PixelFormat.RGBA_8888, 2)
        surface.setOnImageAvailableListener({ frame(it) }, handler)
        reader = surface
        display = runCatching {
            granted.createVirtualDisplay("Saiph phone screen", size.first, size.second, resources.displayMetrics.densityDpi,
                DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR, surface.surface, null, handler)
        }.getOrNull()
        if (display == null) { end(); return }
        notify(true)
        handler.postDelayed(::heartbeat, 500)
    }

    private fun locked() = getSystemService(KeyguardManager::class.java).isKeyguardLocked

    private fun frame(source: ImageReader) {
        val image = runCatching { source.acquireLatestImage() }.getOrNull() ?: return
        try {
            val output = sender ?: return
            if (ended || !output.canAcceptFrame() || !cadence!!.take(SystemClock.elapsedRealtimeNanos())) return
            val plane = image.planes[0]
            val stride = plane.rowStride / plane.pixelStride
            val bitmap = Bitmap.createBitmap(stride, image.height, Bitmap.Config.ARGB_8888)
            bitmap.copyPixelsFromBuffer(plane.buffer)
            val cropped = if (stride != image.width) Bitmap.createBitmap(bitmap, 0, 0, image.width, image.height) else bitmap
            this.output.reset()
            cropped.compress(Bitmap.CompressFormat.JPEG, offer!!.jpegQuality, this.output)
            if (cropped !== bitmap) cropped.recycle()
            bitmap.recycle()
            val jpeg = this.output.toByteArray()
            last = Triple(jpeg, image.width, image.height)
            lastSent = SystemClock.elapsedRealtime()
            output.frame(jpeg, image.width, image.height)
        } catch (_: Exception) { /* Drop one frame; the computer times out if capture stops. */ }
        finally { image.close() }
    }

    /** Lock, rotation and control checks; repeats a still screen so the computer knows it is alive. */
    private fun heartbeat() {
        if (ended) return
        if (locked()) { end(); return }
        val profile = offer ?: return
        val output = sender ?: return
        val (width, height) = realSize()
        val wanted = ScreenProtocol.captureSize(width, height, profile.maxSide, profile.maxPixels)
        if (wanted != size) resize(wanted)
        val control = SaiphInputService.connected()
        if (control != input) { input = control; output.text(ScreenProtocol.state(control)); notify(true) }
        if (!launched && profile.launch.isNotEmpty() && last != null) { launched = true; launch(profile.launch) }
        val still = last
        if (still != null && SystemClock.elapsedRealtime() - lastSent > 1500 && output.canAcceptFrame()) {
            lastSent = SystemClock.elapsedRealtime(); output.frame(still.first, still.second, still.third)
        }
        handler.postDelayed(::heartbeat, 500)
    }

    /** Rotation: the same virtual display with a new surface, never a second consent. */
    private fun resize(wanted: Pair<Int, Int>) {
        val virtual = display ?: return
        val next = ImageReader.newInstance(wanted.first, wanted.second, PixelFormat.RGBA_8888, 2)
        next.setOnImageAvailableListener({ frame(it) }, handler)
        virtual.resize(wanted.first, wanted.second, resources.displayMetrics.densityDpi)
        virtual.surface = next.surface
        reader?.close(); reader = next; size = wanted; last = null
    }

    private fun request(value: ScreenRequest) {
        if (ended || !connected) return
        when (value) {
            is ScreenRequest.Launch -> launch(value.packageName)
            ScreenRequest.Apps -> Thread({ runCatching { sender?.text(ScreenProtocol.apps(PhoneApps.list(this))) } }, "orion-screen-apps").start()
            else -> SaiphInputService.perform(value)
        }
    }

    /**
     * Opens one app from its own launch intent. Android blocks background activity starts
     * unless Saiph's input service is on or "Display over other apps" was allowed; otherwise
     * the owner gets a notification to tap.
     */
    private fun launch(packageName: String) {
        val intent = PhoneApps.launchIntent(this, packageName)
        val ok = intent != null && (SaiphInputService.launch(intent) ||
            (Settings.canDrawOverlays(this) && runCatching { startActivity(intent) }.isSuccess))
        if (!ok && intent != null) ScreenOfferNotice.openApp(this, packageName, intent)
        sender?.text(ScreenProtocol.launched(packageName, ok))
    }

    private fun notification(sharing: Boolean): Notification {
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel(CHANNEL, "Phone screen sharing", NotificationManager.IMPORTANCE_LOW))
        val stop = PendingIntent.getService(this, 1, Intent(this, ScreenShareService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val open = PendingIntent.getActivity(this, 2, Intent(this, PhoneScreenActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val control = if (SaiphInputService.connected()) "Your computer can tap and type." else "View only."
        // Live: red accent (colorized while this foreground service runs), a running time and Stop.
        return NotificationCompat.Builder(this, CHANNEL).setSmallIcon(R.drawable.ic_saiph_tile)
            .setContentTitle(if (sharing) "● Live · Showing your screen on your computer" else "Starting phone screen…")
            .setContentText("$control Protected screens stay black. Locking the phone stops sharing.")
            .setColor(Live.RED).setColorized(sharing).setUsesChronometer(sharing).setWhen(startedAt)
            .setOngoing(true).setOnlyAlertOnce(true).setCategory(NotificationCompat.CATEGORY_SERVICE)
            .setContentIntent(open).addAction(0, "Stop", stop).build()
    }

    private fun notify(sharing: Boolean) {
        if (!ended) getSystemService(NotificationManager::class.java).notify(NOTIFICATION, notification(sharing))
    }

    private fun end() {
        if (ended) return
        ended = true; connected = false
        if (current === this) current = null
        sender?.close(); sender = null
        display?.release(); display = null
        reader?.close(); reader = null
        projection?.let { runCatching { it.unregisterCallback(callback) }; runCatching { it.stop() } }; projection = null
        runCatching { unregisterReceiver(screenOff) }
        last = null
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    override fun onDestroy() { end(); thread.quitSafely(); super.onDestroy() }
}
