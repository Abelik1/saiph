// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.os.Bundle
import android.os.SystemClock
import android.provider.Settings
import android.net.Uri
import android.util.Size
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.LinearLayout
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.core.content.ContextCompat
import java.io.ByteArrayOutputStream
import java.util.concurrent.Executors
import kotlin.math.sqrt

/** Visible, explicit camera sessions only. Leaving the activity ends capture. */
class PhoneCameraActivity : ComponentActivity() {
    private val lock = AppLock(this)
    private lateinit var root: LinearLayout
    private lateinit var status: TextView
    private var offer: CameraOffer? = null
    @Volatile private var sender: CameraSender? = null
    private var provider: ProcessCameraProvider? = null
    private val executor = Executors.newSingleThreadExecutor()
    private var front = true
    @Volatile private var active = false
    private var resumed = false
    private var startAfterResume = false
    @Volatile private var generation = 0
    private val scan = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        val code = result.data?.getStringExtra(OrionQrActivity.CAMERA_CODE) ?: return@registerForActivityResult
        offer = runCatching { CameraOffer.parse(code) }.getOrNull()
        if (offer == null) show("That camera code expired. Start a new session on your computer.")
        else show("Ready. Keep both devices on the same Wi-Fi.")
    }
    private val permission = registerForActivityResult(ActivityResultContracts.RequestPermission()) { allowed ->
        if (allowed) approvedStart() else show("Camera access is off. Allow it in Android Settings, then scan a new code.")
    }
    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        lock.protectWindow()
        window.statusBarColor = Palette.BG; window.navigationBarColor = Palette.BG
        if (!AppPolicy.acknowledged(this)) { finish(); return }
        root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dp(24), dp(48), dp(24), dp(32)); setBackgroundColor(Palette.BG) }
        setContentView(root)
        show()
    }
    private fun show(message: String = "In Saiph on your computer, open Phone → Webcam.") {
        if (!::root.isInitialized) return
        root.removeAllViews()
        root.addView(text("Phone camera", UiType.SCREEN))
        status = text(message, UiType.BODY, Palette.MUTED).apply { setPadding(0, dp(16), 0, dp(20)) }
        root.addView(status)
        if (offer == null) root.addView(button("Scan computer's camera code", true) {
            if (!AppLock.locked(this)) scan.launch(OrionQrActivity.cameraSession(this))
        })
        else {
            root.addView(button(if (front) "Front camera" else "Rear camera", tone = Tone.TONAL) { front = !front; show() })
            root.addView(button("Start camera", true) {
                lock.confirm("Share your camera with the computer you scanned", requireScreenLock = true,
                    failure = { show(it) }) {
                    if (checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) approvedStart()
                    else permission.launch(Manifest.permission.CAMERA)
                }
            })
            root.addView(button("Scan a new code") { offer = null; show() })
        }
        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED)
            root.addView(button("Android camera settings", tone = Tone.TONAL) {
                startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName")))
            })
        root.addView(button("Close") { finish() })
    }
    private fun approvedStart() {
        startAfterResume = true
        if (resumed) { startAfterResume = false; start() }
    }
    private fun start() {
        val current = offer ?: return
        if (!resumed || AppLock.locked(this) || active) return
        if (System.currentTimeMillis() / 1000 >= current.expires) { offer = null; show("Code expired. Scan a new camera code."); return }
        active = true
        val epoch = ++generation
        root.removeAllViews()
        status = text("Connecting to your computer…", UiType.BODY)
        root.addView(status)
        root.addView(button("Stop camera", tone = Tone.DANGER) { stop(); show("Camera stopped.") })
        val output = CameraSender(current, connected = {
            runOnUiThread { if (active && generation == epoch && resumed) bind(epoch) }
        }, ended = {
            runOnUiThread { if (active && generation == epoch) { stop(); show("Camera disconnected. Scan a new code to reconnect.") } }
        })
        sender = output
        output.connect()
    }
    @Suppress("DEPRECATION")
    private fun bind(epoch: Int) {
        val future = ProcessCameraProvider.getInstance(this)
        future.addListener({
            if (!active || generation != epoch || !resumed) return@addListener
            try {
                val cameras = future.get()
                val view = PreviewView(this).apply { layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f) }
                root.addView(view, 1)
                val preview = Preview.Builder().build().also { it.setSurfaceProvider(view.surfaceProvider) }
                val analysis = ImageAnalysis.Builder().setTargetResolution(Size(1280, 720))
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST).build()
                var last = 0L
                analysis.setAnalyzer(executor) { image ->
                    try {
                        val now = SystemClock.elapsedRealtime()
                        if (!active || generation != epoch || now - last < 66) return@setAnalyzer
                        last = now
                        val bitmap = image.toBitmap()
                        val scale = minOf(1.0, 1280.0 / bitmap.width, 1280.0 / bitmap.height,
                            sqrt((1280.0 * 720.0) / (bitmap.width.toDouble() * bitmap.height)))
                        val bounded = if (scale < 1) Bitmap.createScaledBitmap(bitmap,
                            (bitmap.width * scale).toInt().coerceAtLeast(1), (bitmap.height * scale).toInt().coerceAtLeast(1), true) else bitmap
                        val bytes = ByteArrayOutputStream()
                        bounded.compress(Bitmap.CompressFormat.JPEG, 75, bytes)
                        sender?.frame(bytes.toByteArray(), bounded.width, bounded.height, image.imageInfo.rotationDegrees)
                        if (bounded !== bitmap) bounded.recycle()
                        bitmap.recycle()
                    } catch (_: Exception) { /* Drop a malformed or unavailable frame; the desktop times out. */ }
                    finally { image.close() }
                }
                provider = cameras
                cameras.unbindAll()
                cameras.bindToLifecycle(this, if (front) CameraSelector.DEFAULT_FRONT_CAMERA else CameraSelector.DEFAULT_BACK_CAMERA, preview, analysis)
                window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                status.text = "Camera is on · audio is off. Closing this screen stops sharing."
            } catch (_: Exception) { stop(); show("This camera could not start. Scan a new code and try the other camera.") }
        }, ContextCompat.getMainExecutor(this))
    }
    private fun stop() {
        active = false; startAfterResume = false; generation++
        sender?.close(); sender = null; provider?.unbindAll(); provider = null; offer = null
        window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    }
    override fun onResume() {
        super.onResume(); resumed = true
        if (!::root.isInitialized) return
        lock.open(lockedScreen = { root.removeAllViews(); root.addView(text("Unlock Saiph", UiType.TITLE));
            root.addView(button("Unlock", true) { lock.declined = false; lock.open({}, { show() }) }) }, show = {
            if (startAfterResume) { startAfterResume = false; start() } else if (!active) show()
        })
    }
    override fun onPause() { resumed = false; if (active) { stop(); show("Camera stopped when you left this screen.") }; super.onPause() }
    override fun onStop() { lock.stopped(); super.onStop() }
    override fun onDestroy() { stop(); executor.shutdownNow(); super.onDestroy() }
}
