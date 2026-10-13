package sefirah.network.orion

import android.content.Context
import android.content.Intent
import androidx.core.content.ContextCompat
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonPrimitive
import sefirah.domain.interfaces.NetworkManager
import sefirah.domain.model.*
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class OrionNetworkManager @Inject constructor(private val context: Context, private val link: OrionLink, private val peer: OrionPeer) : NetworkManager {
    override fun startService() {
        // Paused from the widget or Settings: nothing starts, including after a reboot.
        if (OrionPause.paused(context)) { stopService(); return }
        if (hostedEnabled()) {
            context.stopService(Intent(context, OrionLinkService::class.java))
            ContextCompat.startForegroundService(context, Intent().setClassName(context, "com.orionmini.mobile.HostedSyncService"))
            return
        }
        if (context.getSharedPreferences("orion", Context.MODE_PRIVATE).contains("device_id"))
            ContextCompat.startForegroundService(context, Intent(context, OrionLinkService::class.java))
    }
    override fun stopService() { context.stopService(Intent(context, OrionLinkService::class.java)); context.stopService(Intent().setClassName(context, "com.orionmini.mobile.HostedSyncService")) }
    private fun hostedEnabled() = context.getSharedPreferences("orion_hosted", 0).getBoolean("enabled", false)
    // LAN certificates and mDNS never establish Orion trust. Pair only through the hub.
    override suspend fun connectPaired(device: PairedDevice) { startService() }
    override suspend fun connectTo(connectionDetails: ConnectionDetails) { throw UnsupportedOperationException("Use Saiph QR pairing") }
    override suspend fun disconnect(deviceId: String) { stopService() }
    override suspend fun approveDeviceConnection(deviceId: String) { throw UnsupportedOperationException("Use Saiph QR pairing") }
    override suspend fun rejectDeviceConnection(deviceId: String) {}
    override fun broadcastMessage(message: SocketMessage) { sendMessage("", message) }
    override fun sendMessage(deviceId: String, message: SocketMessage): Boolean {
        if (hostedEnabled()) return when (message) {
            is ClipboardInfo -> if (clipboardEnabled() && message.clipboardType == "text/plain") HostedFeatureBridge.send("clipboard.text", buildJsonObject { put("text", message.content) }) else false
            is NotificationInfo -> if (message.infoType == NotificationInfoType.Removed)
                HostedFeatureBridge.send("notification.remove", buildJsonObject { put("type", "notification.remove"); put("key", message.notificationKey) })
            else HostedFeatureBridge.send("notification.upsert", buildJsonObject {
                put("type", "notification.upsert"); put("notification", buildJsonObject {
                    put("key", message.notificationKey); put("app", (message.appName ?: "Phone").take(120))
                    put("title", message.title.orEmpty().take(512)); put("text", message.text.orEmpty().take(4096)); put("timestamp", message.timestampMillis.coerceAtLeast(0))
                })
            })
            else -> false
        }
        // Later phases wire the retained modules individually, with capability and action checks.
        val target = deviceId.takeIf { it.isNotBlank() }
        OrionPhoneFeatures.send(link,target,message)?.let { return it }
        if (message is PlaybackInfo) return OrionPhoneFeatures.media.update(message)?.let { link.publish("media.state", it) } ?: true
        return when (message) {
            is ClipboardInfo -> if(clipboardEnabled() && message.clipboardType=="text/plain") peer.sendText(message.content) else false
            is BatteryState -> link.publish("battery", buildJsonObject {
                put("battery_level", message.batteryLevel.coerceIn(0, 100)); put("is_charging", message.isCharging)
            }, target)
            is NotificationInfo -> if (message.infoType == NotificationInfoType.Removed)
                link.publish("notification.remove", buildJsonObject { put("key", message.notificationKey) }, target)
            else link.publish("notification.upsert", buildJsonObject {
                put("key", message.notificationKey); put("app", (message.appName ?: "Phone").take(240))
                put("package", (message.appPackage ?: "unknown").take(240)); put("title", message.title.orEmpty().take(512))
                put("text", message.text.orEmpty().take(4096)); put("timestamp", message.timestampMillis.coerceAtLeast(0))
                put("silent", message.infoType == NotificationInfoType.Active)
                message.replyResultKey?.let { put("reply_key", it.take(240)) }
                put("actions", JsonArray(message.actions.take(10).map { action -> buildJsonObject {
                    put("index", action.actionIndex); put("label", action.label.orEmpty().take(120))
                } }))
            }, target)
            else -> false
        }
    }
    override fun reconcileNotifications(keys: List<String>) {
        link.publish("notification.sync", buildJsonObject { put("keys", JsonArray(keys.map(::JsonPrimitive))) })
    }
    override fun refreshCapabilities() { link.refreshCapabilities() }
    private fun clipboardEnabled() = context.getSharedPreferences("orion", Context.MODE_PRIVATE).getBoolean("clipboard_enabled",true)
    override fun sendClipboardFile(mime: String, file: java.io.File): Boolean {
        if (hostedEnabled() || !clipboardEnabled()) { file.delete(); return false }
        return peer.sendFile(mime,file)
    }
}
