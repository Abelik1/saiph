// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.content.res.Configuration
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
import androidx.camera.core.UseCase
import androidx.camera.core.resolutionselector.AspectRatioStrategy
import androidx.camera.core.resolutionselector.ResolutionSelector
import androidx.camera.core.resolutionselector.ResolutionStrategy
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
    private lateinit var frame: ScreenFrame
    private lateinit var status: TextView
    private var offer: CameraOffer? = null
    /** The approved computer that sent this offer through Saiph Cloud; null for a scanned code. */
    private var computer: String? = null
    @Volatile private var sender: CameraSender? = null
    private var provider: ProcessCameraProvider? = null
    private var useCases: List<UseCase> = emptyList()
    private val executor = Executors.newSingleThreadExecutor()
    private var front = true
    @Volatile private var active = false
    private var resumed = false
    private var startAfterResume = false
    /** Allow was chosen in the request pop-up or notification: verify once this page is resumed. */
    private var confirmAfterResume = false
    @Volatile private var generation = 0
    private val scan = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        val code = result.data?.getStringExtra(OrionQrActivity.CAMERA_CODE) ?: return@registerForActivityResult
        offer = runCatching { CameraOffer.parse(code) }.getOrNull(); computer = null
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
        page(scrolling = true)
        show()
        receive(intent)
    }
    override fun onNewIntent(intent: Intent) { super.onNewIntent(intent); setIntent(intent); receive(intent) }
    /** Opened from a camera request: the intent names an offer ID; the invitation stays in memory. */
    private fun receive(intent: Intent?) {
        if (intent?.getBooleanExtra(Live.EXTRA_STOP, false) == true) {
            intent.removeExtra(Live.EXTRA_STOP)
            if (active) { stop(); show("Camera stopped.") }
            return
        }
        val id = intent?.getStringExtra(CameraRequests.EXTRA_OFFER) ?: return
        val allow = intent.getBooleanExtra(RequestPrompts.EXTRA_ALLOW, false)
        intent.removeExtra(CameraRequests.EXTRA_OFFER); intent.removeExtra(RequestPrompts.EXTRA_ALLOW)
        // Opened from the request: its notification and pop-up go, even if a camera is already on.
        RequestPrompts.taken(this, "camera")
        if (active || !::root.isInitialized) return
        val pending = SessionOffers.take(id)
        if (pending == null || pending.source !in HostedRuntime.get(this).subscribers()) {
            offer = null; computer = null; show("That camera request expired. Start the camera again on your computer."); return
        }
        offer = pending.offer.camera; computer = pending.computer
        show()
        // Allow in the pop-up or notification goes straight to confirming it's you.
        if (allow) { if (resumed && !AppLock.locked(this)) confirmStart() else confirmAfterResume = true }
    }
    /** Owner verification (screen lock required), then Android camera access, then start. */
    private fun confirmStart() {
        lock.confirm(computer?.let { "Share your camera with $it" } ?: "Share your camera with the computer you scanned", requireScreenLock = true,
            failure = { show(it) }) {
            if (checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) approvedStart()
            else permission.launch(Manifest.permission.CAMERA)
        }
    }
    private fun idle() = computer?.takeIf { offer != null }?.let { "$it wants to use this phone as its webcam. Audio stays off." }
        ?: "Use this phone as your computer's webcam on the same Wi-Fi."
    /**
     * The shared frame: Back in the top corner (it leaves, which stops any capture), the title,
     * then this state's content. A live preview needs the full height, so it does not scroll.
     */
    private fun page(scrolling: Boolean) {
        frame = ScreenFrame(this, "Phone camera", back = ::finish, scrolling = scrolling)
        root = frame.content
    }
    private fun show(message: String = idle()) {
        if (!::root.isInitialized) return
        page(scrolling = true)
        status = text(message, UiType.BODY, Palette.MUTED).apply { setPadding(dp(2), dp(4), 0, dp(8)) }
        root.addView(status)
        if (offer == null) {
            // One main action, so the screen shows what happens around it.
            root.addView(stepGuide(Step(StepPicture.COMPUTER_TAB, "On your computer, open Saiph → Phone → Webcam."),
                Step(StepPicture.SCAN_CODE, "Scan the code your computer shows."),
                Step(StepPicture.VERIFY, "Confirm it's you on this phone."),
                Step(StepPicture.STREAM, "Your computer receives this phone's camera. Audio stays off.")))
            frame.dockActions(button("Scan computer's camera code", true) {
                if (!AppLock.locked(this)) scan.launch(OrionQrActivity.cameraSession(this))
            })
        }
        else {
            root.addView(card().apply {
                addView(text(if (front) "Front camera" else "Rear camera", UiType.BODY, bold = true))
                addView(text("You can switch before starting.", UiType.META, Palette.MUTED))
                addView(compactActions(compactButton(if (front) "Use rear camera" else "Use front camera") { front = !front; show() }))
            })
            frame.dockActions(button("Start camera", true) { confirmStart() })
            frame.dock.addView(buttonRow(setupLink(if (computer != null) "Not now" else "Scan a new code") { offer = null; computer = null; show() }))
        }
        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED)
            root.addView(settingsRow(null, "Android camera settings", "Saiph asks for camera access when you start the camera.", external = true) {
                startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName")))
            })
    }
    private fun approvedStart() {
        startAfterResume = true
        if (resumed) { startAfterResume = false; start() }
    }
    private fun start() {
        val current = offer ?: return
        if (!resumed || AppLock.locked(this) || active) return
        if (System.currentTimeMillis() / 1000 >= current.expires) { offer = null; computer = null; show("This camera request expired. Start the camera again on your computer."); return }
        active = true
        RequestPrompts.taken(this, "camera")
        val epoch = ++generation
        page(scrolling = false)
        status = text("Connecting to your computer…", UiType.BODY)
        root.addView(status)
        root.addView(buttonRow(button("Stop camera", tone = Tone.DANGER) { stop(); show("Camera stopped.") }))
        val output = CameraSender(current, connected = {
            runOnUiThread { if (active && generation == epoch && resumed) bind(epoch) }
        }, ended = {
            runOnUiThread { if (active && generation == epoch) { stop(); show("Camera disconnected. Start the camera again on your computer to reconnect.") } }
        })
        sender = output
        output.connect()
    }
    @Suppress("DEPRECATION")
    private fun bind(epoch: Int) {
        val profile = offer ?: return
        val output = sender ?: return
        val future = ProcessCameraProvider.getInstance(this)
        future.addListener({
            if (!active || generation != epoch || !resumed) return@addListener
            try {
                val cameras = future.get()
                val view = PreviewView(this).apply { layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f) }
                root.addView(view, 1)
                // Sizes are in sensor (landscape) orientation. Without an explicit 16:9 bound
                // the deprecated target resolution let a Galaxy A55 front camera pick a
                // 2448×2448 analysis stream, forcing per-frame bitmap resampling at ~8 fps.
                val preview = Preview.Builder().setResolutionSelector(selector(Size(1280, 720))).build()
                    .also { it.setSurfaceProvider(view.surfaceProvider) }
                val analysis = ImageAnalysis.Builder().setResolutionSelector(selector(Size(profile.width, profile.height)))
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST).build()
                val encoder = CameraJpeg()
                val cadence = CameraCadence(profile.fps)
                analysis.setAnalyzer(executor) { image ->
                    try {
                        val now = SystemClock.elapsedRealtimeNanos()
                        if (!active || generation != epoch || !output.canAcceptFrame() || !cadence.take(now)) return@setAnalyzer
                        if (image.width % 2 == 0 && image.height % 2 == 0 && image.width <= maxOf(profile.width, profile.height)
                            && image.height <= maxOf(profile.width, profile.height) && image.width * image.height <= profile.width * profile.height) {
                            output.frame(encoder.encode(image, profile.jpegQuality), image.width, image.height, image.imageInfo.rotationDegrees)
                            return@setAnalyzer
                        }
                        // CameraX may choose a larger supported sensor size.
                        // Only that fallback needs a bitmap and resampling.
                        val bitmap = image.toBitmap()
                        val bound = maxOf(profile.width, profile.height).toDouble()
                        val scale = minOf(1.0, bound / bitmap.width, bound / bitmap.height,
                            sqrt((profile.width.toDouble() * profile.height) / (bitmap.width.toDouble() * bitmap.height)))
                        val bounded = if (scale < 1) Bitmap.createScaledBitmap(bitmap,
                            (bitmap.width * scale).toInt().coerceAtLeast(1), (bitmap.height * scale).toInt().coerceAtLeast(1), true) else bitmap
                        val bytes = ByteArrayOutputStream()
                        bounded.compress(Bitmap.CompressFormat.JPEG, profile.jpegQuality, bytes)
                        output.frame(bytes.toByteArray(), bounded.width, bounded.height, image.imageInfo.rotationDegrees)
                        if (bounded !== bitmap) bounded.recycle()
                        bitmap.recycle()
                    } catch (_: Exception) { /* Drop a malformed or unavailable frame; the desktop times out. */ }
                    finally { image.close() }
                }
                provider = cameras
                useCases = listOf(preview, analysis)
                rotate()
                cameras.unbindAll()
                cameras.bindToLifecycle(this, if (front) CameraSelector.DEFAULT_FRONT_CAMERA else CameraSelector.DEFAULT_BACK_CAMERA, preview, analysis)
                window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                // Live: a red banner here and a red ongoing notification with Stop.
                root.addView(liveBanner("Your camera is on" + (computer?.let { " for $it" } ?: " for your computer") + ". Closing this screen stops it."), 0)
                Live.showCamera(this, computer)
                status.text = "Camera is on · ${profile.resolution} · target ${profile.fps} fps · ${profile.quality} quality · audio is off. Closing this screen stops sharing."
            } catch (_: Exception) { stop(); show("This camera could not start. Scan a new code and try the other camera.") }
        }, ContextCompat.getMainExecutor(this))
    }
    private fun selector(bound: Size) = ResolutionSelector.Builder()
        .setAspectRatioStrategy(AspectRatioStrategy.RATIO_16_9_FALLBACK_AUTO_STRATEGY)
        .setResolutionStrategy(ResolutionStrategy(bound, ResolutionStrategy.FALLBACK_RULE_CLOSEST_LOWER_THEN_HIGHER))
        .build()
    private fun stop() {
        active = false; startAfterResume = false; generation++
        sender?.close(); sender = null; provider?.unbindAll(); provider = null; useCases = emptyList(); offer = null; computer = null
        window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        Live.clearCamera(this)
    }
    override fun onResume() {
        super.onResume(); resumed = true
        if (!::root.isInitialized) return
        lock.open(lockedScreen = { page(scrolling = true); root.addView(text("Confirm it's you to open Saiph.", UiType.BODY, Palette.MUTED))
            frame.dockActions(button("Unlock", true) { lock.declined = false; lock.open({}, { show() }) }) }, show = {
            if (startAfterResume) { startAfterResume = false; start() }
            else if (!active) {
                show()
                if (confirmAfterResume) { confirmAfterResume = false; if (offer != null) confirmStart() }
            }
        })
    }
    // The manifest keeps this screen across rotation, so a live session continues;
    // only the frames' rotation metadata follows the new display orientation.
    override fun onConfigurationChanged(newConfig: Configuration) { super.onConfigurationChanged(newConfig); rotate() }
    @Suppress("DEPRECATION") // Activity.display needs API 30; minSdk is 26.
    private fun rotate() {
        val rotation = windowManager.defaultDisplay.rotation
        useCases.forEach { when (it) { is Preview -> it.targetRotation = rotation; is ImageAnalysis -> it.targetRotation = rotation } }
    }
    override fun onPause() { resumed = false; if (active) { stop(); show("Camera stopped when you left this screen.") }; super.onPause() }
    override fun onStop() { lock.stopped(); super.onStop() }
    override fun onDestroy() { stop(); executor.shutdownNow(); super.onDestroy() }
}
