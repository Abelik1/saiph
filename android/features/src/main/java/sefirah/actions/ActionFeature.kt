package sefirah.actions

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import sefirah.Feature
import sefirah.domain.interfaces.DeviceManager
import sefirah.domain.model.ActionInfo
import sefirah.domain.model.DevicePreferences
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class ActionFeature @Inject constructor(
    deviceManager: DeviceManager,
) : Feature(deviceManager) {
    private val _actionsByDevice = MutableStateFlow<Map<String, List<ActionInfo>>>(emptyMap())
    val actionsByDevice: StateFlow<Map<String, List<ActionInfo>>> = _actionsByDevice.asStateFlow()

    private val mutex = Mutex()

    override fun isPrefEnabled(prefs: DevicePreferences) = true

    override suspend fun onStop(deviceId: String) {
        clearDeviceActions(deviceId)
    }

    suspend fun setActions(deviceId: String, actions: List<ActionInfo>) {
        mutex.withLock {
            val currentMap = _actionsByDevice.value.toMutableMap()
            currentMap[deviceId] = actions
            _actionsByDevice.value = currentMap
        }
    }

    suspend fun addAction(deviceId: String, action: ActionInfo) {
        mutex.withLock {
            val currentMap = _actionsByDevice.value.toMutableMap()
            val deviceActions = currentMap.getOrDefault(deviceId, emptyList()).toMutableList()
            val existingIndex = deviceActions.indexOfFirst { it.actionId == action.actionId }
            if (existingIndex >= 0) {
                deviceActions[existingIndex] = action
            } else {
                deviceActions.add(action)
            }
            currentMap[deviceId] = deviceActions
            _actionsByDevice.value = currentMap
        }
    }

    suspend fun clearDeviceActions(deviceId: String) {
        mutex.withLock {
            val currentMap = _actionsByDevice.value.toMutableMap()
            currentMap.remove(deviceId)
            _actionsByDevice.value = currentMap
        }
    }
}
