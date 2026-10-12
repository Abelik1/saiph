package sefirah.status

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import sefirah.Feature
import sefirah.domain.interfaces.DeviceManager
import sefirah.domain.model.BatteryState
import sefirah.domain.model.DevicePreferences
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Holds volatile status reported by connected remote devices (e.g. the desktop's
 * battery level). State is runtime-only and keyed by deviceId; cleared on disconnect.
 */
@Singleton
class RemoteDeviceStatusFeature @Inject constructor(
    deviceManager: DeviceManager,
) : Feature(deviceManager) {
    private val _batteryByDevice = MutableStateFlow<Map<String, BatteryState>>(emptyMap())
    val batteryByDevice: StateFlow<Map<String, BatteryState>> = _batteryByDevice.asStateFlow()

    override fun isPrefEnabled(prefs: DevicePreferences) = true

    override suspend fun onStop(deviceId: String) {
        clearDeviceStatus(deviceId)
    }

    fun updateBattery(deviceId: String, state: BatteryState) {
        _batteryByDevice.update { it + (deviceId to state) }
    }

    fun clearDeviceStatus(deviceId: String) {
        _batteryByDevice.update { it - deviceId }
    }
}
