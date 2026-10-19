package sefirah.domain.interfaces

import sefirah.domain.model.ConnectionDetails
import sefirah.domain.model.PairedDevice
import sefirah.domain.model.SocketMessage

interface NetworkManager {
    fun startService()
    fun stopService()
    suspend fun connectPaired(device: PairedDevice)
    suspend fun connectTo(connectionDetails: ConnectionDetails)
    suspend fun disconnect(deviceId: String)
    fun broadcastMessage(message: SocketMessage)
    /** Hub transport's authoritative active-key reconciliation, not LAN discovery. */
    fun reconcileNotifications(keys: List<String>) {}
    fun refreshCapabilities() {}
    /** Direct mesh clipboard/image offer; local file ownership passes to the transport. */
    fun sendClipboardFile(mime: String, file: java.io.File): Boolean = false
    val clipboardFileLimit: Long get() = 2L * 1024 * 1024 * 1024
    /** Current approved identity for the already authorized debugging worker. */
    fun clipboardDeviceId(): String? = null
    val clipboardConnectionMode: String get() = "self_hosted"
    /** @return false if there is no live connection */
    fun sendMessage(deviceId: String, message: SocketMessage): Boolean
    suspend fun approveDeviceConnection(deviceId: String)
    suspend fun rejectDeviceConnection(deviceId: String)
}
