package sefirah.network.orion

import android.app.*
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.IBinder
import android.os.PowerManager
import androidx.core.app.NotificationCompat
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.*
import sefirah.status.DeviceControlHandler
import sefirah.notification.NotificationFeature
import sefirah.clipboard.ClipboardFeature
import sefirah.domain.model.NotificationAction
import sefirah.domain.model.NotificationReply
import kotlinx.serialization.json.*
import javax.inject.Inject

interface OrionCompanion {
    suspend fun refresh()
    suspend fun checkUpdate()
}

@AndroidEntryPoint
class OrionLinkService : Service() {
    @Inject lateinit var link: OrionLink
    @Inject lateinit var controls: DeviceControlHandler
    @Inject lateinit var companion: OrionCompanion
    @Inject lateinit var notifications: NotificationFeature
    @Inject lateinit var clipboard: ClipboardFeature
    @Inject lateinit var peer: OrionPeer
    @Inject lateinit var phoneFeatures: OrionPhoneFeatures
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val continuity by lazy { OrionContinuity(this) }
    private var clipboardEnabled = false
    // The owner's own Do Not Disturb changes are shared; applying a shared state is not.
    private val interruptionFilter = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            scope.launch { runCatching { continuity.systemChanged { type, payload -> link.publish(type, payload) } } }
        }
    }
    override fun onCreate() {
        super.onCreate()
        Api.migrateMesh(this)
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel("orion_link", "Saiph status", NotificationManager.IMPORTANCE_LOW))
        startForeground(42, notification("Starting automatically"))
        controls.start()
        androidx.core.content.ContextCompat.registerReceiver(this, interruptionFilter, IntentFilter(NotificationManager.ACTION_INTERRUPTION_FILTER_CHANGED), androidx.core.content.ContextCompat.RECEIVER_NOT_EXPORTED)
        scope.launch { notifications.enable("") }
        scope.launch { link.status.collect { manager.notify(42, notification(it)) } }
        val receipts = CommandReceipts(this)
        scope.launch { link.run(onConnected = { controls.sendDeviceStatus(""); notifications.sendActiveNotifications(""); scope.launch { phoneFeatures.connected() };scope.launch { runCatching { continuity.restore() } } }, onEvent = { event ->
            continuity.event(event)
            runCatching { OrionRemote.receive(event) }
            if(event["type"]?.jsonPrimitive?.content in setOf("sms.open","sms.send","call.command","photo.request","file.offer")) phoneFeatures.receive(event)
            if(event["type"]?.jsonPrimitive?.content=="clipboard" && getSharedPreferences("orion",0).getBoolean("clipboard_enabled",true)) peer.receiveClipboard(event,clipboard)
            if (event["type"]?.jsonPrimitive?.content == "phone.ring" && receipts.claim(event.getValue("id").jsonPrimitive.content)) OrionRing.start(this@OrionLinkService)
            if (event["type"]?.jsonPrimitive?.content == "notification.command") {
                val payload = event.getValue("payload").jsonObject
                val key = payload.getValue("key").jsonPrimitive.content
                val operation = payload.getValue("operation").jsonPrimitive.content
                val id = event.getValue("id").jsonPrimitive.content
                if (receipts.claim(id) && notifications.isAvailable()) {
                    when (operation) {
                        "dismiss" -> notifications.removeNotification(key)
                        "open" -> notifications.openNotification(key)
                        "action" -> notifications.performNotificationAction(NotificationAction(key, actionIndex = payload.getValue("index").jsonPrimitive.int))
                        "reply" -> notifications.performReplyAction(NotificationReply(key, payload.getValue("reply_key").jsonPrimitive.content, payload.getValue("text").jsonPrimitive.content))
                    }
                }
            }
            getSharedPreferences("orion", MODE_PRIVATE).edit().putLong("last_event_at", System.currentTimeMillis()).apply()
        }) }
        scope.launch {
            var nextUpdate = 0L
            while (isActive) {
                updateClipboard()
                runCatching { continuity.tick() }
                if (link.status.value == "Online") controls.sendDeviceStatus("")
                if(link.status.value=="Online") { runCatching { peer.start() };runCatching { phoneFeatures.refresh() } }
                else runCatching { phoneFeatures.refreshPermissions() }
                link.refreshCapabilities()
                manager.notify(42, notification(link.status.value))
                try {
                    companion.refresh()
                    if (System.currentTimeMillis() >= nextUpdate) {
                        companion.checkUpdate(); nextUpdate = System.currentTimeMillis() + 6 * 60 * 60 * 1000
                    }
                } catch (e: CancellationException) { throw e }
                catch (_: Exception) { /* Recovered on the next poll, without logging personal data. */ }
                delay(15000)
            }
        }
    }
    private suspend fun updateClipboard() {
        val enabled=getSharedPreferences("orion",0).getBoolean("clipboard_enabled",true)
        if(enabled==clipboardEnabled)return
        if(enabled)clipboard.enable("") else clipboard.disable("")
        clipboardEnabled=enabled;link.refreshCapabilities()
    }
    private fun notification(state: String): Notification {
        val intent = packageManager.getLaunchIntentForPackage(packageName)!!
        val power = getSystemService(PowerManager::class.java)
        val message = when {
            !power.isIgnoringBatteryOptimizations(packageName) -> "Battery setting needs attention. Tap for settings."
            !getSystemService(NotificationManager::class.java).areNotificationsEnabled() -> "Saiph notifications need attention. Tap for settings."
            else -> state
        }
        // A future feature's permission must not repeatedly reopen completed Phase 2 setup.
        val prefs=getSharedPreferences("orion", MODE_PRIVATE)
        val openSetup=SetupNavigation.notificationOpensSetup(prefs.getBoolean("setup_done",false),prefs.getBoolean("setup_deferred",false))
        intent.putExtra("setup", message != state && openSetup)
        intent.putExtra("settings", message != state && !openSetup)
        val open = PendingIntent.getActivity(this, 42, intent, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        return NotificationCompat.Builder(this, "orion_link").setSmallIcon(android.R.drawable.ic_menu_share)
            .setContentTitle("Saiph").setContentText(message).setContentIntent(open).setOngoing(true).setOnlyAlertOnce(true).build()
    }
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        // Activity resume after OS permission changes reaches an existing service too.
        link.refreshCapabilities()
        scope.launch { runCatching { phoneFeatures.refreshPermissions() } }
        return START_STICKY
    }
    override fun onBind(intent: Intent?): IBinder? = null
    override fun onDestroy() {
        runCatching { unregisterReceiver(interruptionFilter) }
        controls.stop()
        scope.cancel()
        // Finish bounded teardown before a replacement service can start.
        // Launching on an independent scope races a new service's enable hooks.
        runBlocking(Dispatchers.IO) { notifications.disable("");clipboard.disable("");peer.stop();phoneFeatures.stop() }
        super.onDestroy()
    }
}
