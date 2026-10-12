/*
 * Acknowledgment:
 * Portions of this code are adapted from XClipper by Kaustubh Patange.
 * Licensed under the Apache License 2.0.
 */

package sefirah.clipboard

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.AccessibilityServiceInfo
import android.os.Build
import android.util.Log
import android.view.accessibility.AccessibilityEvent
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import sefirah.clipboard.extensions.LanguageDetector
import sefirah.domain.interfaces.DeviceManager
import sefirah.worker.WorkerManager
import javax.inject.Inject

/**
 * Accessibility-based clipboard copy detection (XClipper-style heuristics).
 * Raises [ClipboardChangeActivity] so the app can read the clipboard on Android 10+
 * when the shell worker is not running.
 */
@AndroidEntryPoint
class ClipboardAccessibilityService : AccessibilityService() {
    @Inject lateinit var deviceManager: DeviceManager
    @Inject lateinit var workerManager: WorkerManager
    @Inject lateinit var clipboardFeature: ClipboardFeature

    private lateinit var clipboardDetector: ClipboardDetection

    private var runForNextEventAlso = false
    private var lastDetectionTimeMs = 0L
    private val minDetectionInterval = 100L

    override fun onCreate() {
        super.onCreate()
        clipboardDetector = ClipboardDetection(LanguageDetector.getCopyForLocale(applicationContext))
    }

    override fun onServiceConnected() {
        super.onServiceConnected()

        serviceInfo = AccessibilityServiceInfo().apply {
            eventTypes = MONITORED_EVENTS
            feedbackType = AccessibilityServiceInfo.FEEDBACK_ALL_MASK
            flags = flags or AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS
            notificationTimeout = 120
        }
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        // Prefer live shell worker — avoid duplicate accessibility launches.
        if (workerManager.isWorkerAlive()) return
        if (!isAnyDeviceConnected()) return
        if (clipboardFeature.activeDeviceIds.isEmpty()) return

        try {
            if (event?.eventType != null) {
                clipboardDetector.addEvent(event.eventType)
            }
            val currentTimeMs = System.currentTimeMillis()

            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q &&
                clipboardDetector.getSupportedEventTypes(event)
            ) {
                if (currentTimeMs - lastDetectionTimeMs < minDetectionInterval) {
                    Log.d(TAG, "Ignoring duplicate detection")
                    return
                }

                lastDetectionTimeMs = currentTimeMs
                runForNextEventAlso = true
                Log.d(TAG, "Running for first time")
                launchFloatingActivity()
                return
            }

            if (runForNextEventAlso) {
                Log.d(TAG, "Running for second time")
                runForNextEventAlso = false
                launchFloatingActivity()
            }
        } catch (e: Exception) {
            Log.e(TAG, "Accessibility Service Error", e)
        }
    }

    override fun onInterrupt() {}

    private fun isAnyDeviceConnected(): Boolean = runBlocking {
        deviceManager.pairedDevices.first().any {
            it.connectionState.isConnected || it.connectionState.isConnecting
        }
    }

    private val lock = Any()
    private fun launchFloatingActivity() = synchronized(lock) {
        ClipboardChangeActivity.launch(applicationContext)
    }

    companion object {
        private const val TAG = "ClipboardAccessibilityService"

        private const val MONITORED_EVENTS = AccessibilityEvent.TYPE_VIEW_CLICKED or
            AccessibilityEvent.TYPE_VIEW_FOCUSED or
            AccessibilityEvent.TYPE_VIEW_LONG_CLICKED or
            AccessibilityEvent.TYPE_VIEW_SELECTED or
            AccessibilityEvent.TYPE_VIEW_TEXT_CHANGED or
            AccessibilityEvent.TYPE_VIEW_TEXT_SELECTION_CHANGED or
            AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED or
            AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED or
            AccessibilityEvent.TYPE_NOTIFICATION_STATE_CHANGED
    }
}
