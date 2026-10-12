package sefirah.media

import android.content.ComponentName
import android.content.Context
import android.media.MediaMetadata
import android.media.session.MediaController
import android.media.session.MediaSessionManager
import android.media.session.PlaybackState
import android.os.Handler
import android.os.Looper
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import android.util.Log
import androidx.core.content.ContextCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import sefirah.common.util.isNotificationListenerEnabled
import sefirah.BoundFeature
import sefirah.domain.interfaces.DeviceManager
import sefirah.domain.interfaces.NetworkManager
import sefirah.domain.interfaces.NotificationCallback
import sefirah.domain.interfaces.PreferencesRepository
import sefirah.domain.model.DevicePreferences
import sefirah.domain.model.MediaAction
import sefirah.domain.model.MediaActionType
import sefirah.domain.model.PlaybackInfo
import sefirah.domain.model.PlaybackInfoType
import sefirah.notification.NotificationListener
import java.util.concurrent.ConcurrentHashMap
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class PlaybackFeature @Inject constructor(
    private val context: Context,
    deviceManager: DeviceManager,
    private val networkManager: NetworkManager,
    private val preferencesRepository: PreferencesRepository,
) : BoundFeature(deviceManager), NotificationCallback {
    private val tag = "MediaSessionTracker"
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    
    private var mediaSessionManager: MediaSessionManager? = null
    private var sessionChangeListener: MediaSessionChangeListener? = null

    private val mediaSessions = ConcurrentHashMap<String, MediaSession>()
    private val sessionCallbacks = ConcurrentHashMap<String, MediaSessionCallback>()

    @Volatile
    private var notificationListenerConnected = false
    @Volatile
    private var spotifyRunning = false

    private val handler = Handler(Looper.getMainLooper())

    override fun isPrefEnabled(prefs: DevicePreferences) = prefs.mediaPlayerControl

    override fun hasPermissions(): Boolean = isNotificationListenerEnabled(context)

    override suspend fun onStart() {
        initializeManager()
    }

    override suspend fun onStop() {
        release()
    }

    override suspend fun onStart(deviceId: String) {
        sendActiveSessions(deviceId)
    }

    private fun initializeManager() {
        if (mediaSessionManager != null) return
        try {
            val manager = ContextCompat.getSystemService(context, MediaSessionManager::class.java) ?: return

            val notificationListener = ComponentName(context, NotificationListener::class.java)
            mediaSessionManager = manager
            sessionChangeListener = MediaSessionChangeListener()
            manager.addOnActiveSessionsChangedListener(sessionChangeListener!!, notificationListener, handler)

            val controllers = manager.getActiveSessions(notificationListener)
            createSessions(controllers)
        } catch (e: Exception) {
            // Listener may not be connected yet — retry from onListenerConnected
            Log.d(tag, "Could not initialize media session manager: ${e.message}")
        }
    }
    
    override fun onListenerConnected(service: NotificationListenerService) {
        notificationListenerConnected = true
        try {
            val isSpotifyActive = service.activeNotifications?.any { it.isSpotify() } == true
            spotifyRunning = isSpotifyActive
        } catch (e: SecurityException) {
            Log.w(tag, "Failed to inspect active notifications for Spotify", e)
        }
        if (enabledDevices.isNotEmpty()) {
            initializeManager()
            enabledDevices.forEach { sendActiveSessions(it) }
        }
    }

    override fun onListenerDisconnected() {
        notificationListenerConnected = false
        spotifyRunning = false
        release()
    }
    
    override fun onNotificationPosted(notification: StatusBarNotification) {
        if (!notification.isSpotify()) return
        spotifyRunning = true
    }
    
    override fun onNotificationRemoved(notification: StatusBarNotification) {
        if (!notification.isSpotify()) return
        spotifyRunning = false
    }

    fun release() {
        mediaSessionManager?.let { manager ->
            sessionChangeListener?.let { listener ->
                manager.removeOnActiveSessionsChangedListener(listener)
            }
        }

        mediaSessions.keys.toList().forEach { packageName ->
            sessionCallbacks[packageName]?.let { cb ->
                mediaSessions[packageName]?.controller?.unregisterCallback(cb)
            }
        }
        sessionCallbacks.clear()
        mediaSessions.clear()
        sessionChangeListener = null
        mediaSessionManager = null
    }

    private fun createSessions(controllers: List<MediaController>?) {
        if (controllers == null) return

        mediaSessions.keys.toList().forEach { packageName ->
            sessionCallbacks[packageName]?.let { cb ->
                mediaSessions[packageName]?.controller?.unregisterCallback(cb)
            }
        }
        sessionCallbacks.clear()
        mediaSessions.clear()

        controllers.forEach { controller ->
            if (controller.packageName == context.packageName) return@forEach
            try {
                val pkg = controller.packageName
                val appName = getAppName(pkg)
                val player = MediaSession(controller, appName)
                val callback = MediaSessionCallback(this, pkg)
                controller.registerCallback(callback, handler)
                mediaSessions[pkg] = player
                sessionCallbacks[pkg] = callback
            } catch (e: Exception) {
                Log.e(tag, "Failed to create session for ${controller.packageName}", e)
            }
        }
    }

    fun onSessionMetadataChanged(packageName: String) {
        val session = mediaSessions[packageName] ?: return
        sendToDevices(session.toPlaybackSession())
    }

    fun onSessionPlaybackStateChanged(packageName: String) {
        val session = mediaSessions[packageName] ?: return
        val message = PlaybackInfo(
            infoType = PlaybackInfoType.PlaybackUpdate,
            source = packageName,
            isPlaying = session.isPlaying(),
            position = session.getPosition().toDouble()
        )
        sendToDevices(message)
    }

    private fun getAppName(packageName: String): String {
        return try {
            val packageManager = context.packageManager
            val applicationInfo = packageManager.getApplicationInfo(packageName, 0)
            packageManager.getApplicationLabel(applicationInfo).toString()
        } catch (e: Exception) {
            Log.w(tag, "Failed to get app name for $packageName", e)
            packageName
        }
    }

    fun getActivePackageNames(): Set<String> = mediaSessions.keys

    fun isSpotifyActive(): Boolean = spotifyRunning
    
    /**
     * Handle incoming PlaybackAction from connected devices to control
     * Android media sessions. Delegates to the matching [MediaSession].
     */
    suspend fun handlePlaybackAction(deviceId: String, action: MediaAction) {
        if (!preferencesRepository.readMediaPlayerControlSettingsForDevice(deviceId).first()) return

        if (!mediaSessions.containsKey(action.source)) {
            Log.d(tag, "MediaAction source ${action.source} not found in Android sessions, ignoring")
            return
        }

        val packageName = action.source
        val player = mediaSessions[packageName] ?: return

        try {
            when (action.actionType) {
                MediaActionType.Play -> if (player.canPlay()) player.play()
                MediaActionType.Pause -> if (player.canPause()) player.pause()
                MediaActionType.Next -> if (player.canGoNext()) player.next()
                MediaActionType.Previous -> if (player.canGoPrevious()) player.previous()
                MediaActionType.Seek -> if (player.canSeek() && action.value != null) {
                    player.setPosition(action.value!!.toLong())
                }
                MediaActionType.VolumeUpdate -> if (action.value != null) {
                    val volumePercent = (action.value!!).toInt().coerceIn(0, 100)
                    player.setVolume(volumePercent)
                    onSessionPlaybackStateChanged(packageName)
                }
                else -> Log.d(tag, "Action ${action.actionType} not supported for Android sessions")
            }
            Log.d(tag, "Handled MediaAction for Android session: ${action.source}")
        } catch (e: Exception) {
            Log.e(tag, "Failed to handle playback action for $packageName", e)
        }
    }

    fun sendActiveSessions(deviceId: String) {
        scope.launch {
            mediaSessions.values.toList().forEach { session ->
                val msg = session.toPlaybackSession()
                networkManager.sendMessage(deviceId, msg)
            }
        }
    }
    
    private fun sendToDevices(session: PlaybackInfo) {
        if (enabledDevices.isEmpty()) return
        scope.launch {
            enabledDevices.forEach { deviceId ->
                networkManager.sendMessage(deviceId, session)
            }
        }
    }

    private inner class MediaSessionChangeListener : MediaSessionManager.OnActiveSessionsChangedListener {
        override fun onActiveSessionsChanged(controllers: MutableList<MediaController>?) {
            controllers?.let {
                createSessions(controllers)
            }
        }
    }

    class MediaSessionCallback(val service: PlaybackFeature, val packageName: String) : MediaController.Callback() {
        override fun onMetadataChanged(metadata: MediaMetadata?) {
            service.onSessionMetadataChanged(packageName)
        }

        override fun onPlaybackStateChanged(state: PlaybackState?) {
            service.onSessionPlaybackStateChanged(packageName)
        }
    }

    private fun StatusBarNotification.isSpotify(): Boolean =
        this.packageName == SPOTIFY_PACKAGE_NAME

    companion object {
        private const val SPOTIFY_PACKAGE_NAME = "com.spotify.music"
    }
}