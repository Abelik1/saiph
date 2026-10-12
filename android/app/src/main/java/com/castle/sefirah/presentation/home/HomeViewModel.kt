package com.castle.sefirah.presentation.home

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import sefirah.domain.interfaces.PreferencesRepository
import sefirah.domain.model.ActionInfo
import sefirah.domain.model.AudioAction
import sefirah.domain.model.AudioActionType
import sefirah.domain.model.AudioDeviceInfo
import sefirah.domain.model.BatteryState
import sefirah.domain.model.MediaAction
import sefirah.domain.model.MediaActionType
import sefirah.domain.model.PlaybackInfo
import sefirah.domain.model.SocketMessage
import sefirah.domain.interfaces.DeviceManager
import sefirah.domain.interfaces.NetworkManager
import sefirah.actions.ActionFeature
import sefirah.media.RemotePlaybackFeature
import sefirah.status.RemoteDeviceStatusFeature
import javax.inject.Inject

@HiltViewModel
class HomeViewModel @Inject constructor(
    private val remotePlaybackFeature: RemotePlaybackFeature,
    private val deviceManager: DeviceManager,
    private val networkManager: NetworkManager,
    actionFeature: ActionFeature,
    remoteDeviceStatusFeature: RemoteDeviceStatusFeature,
    preferencesRepository: PreferencesRepository,
) : ViewModel() {

    val batteryByDevice: StateFlow<Map<String, BatteryState>> =
        remoteDeviceStatusFeature.batteryByDevice

    val activeSessions: StateFlow<List<PlaybackInfo>> = deviceManager.selectedDeviceId
        .flatMapLatest { deviceId ->
            remotePlaybackFeature.activeSessionsByDevice.map { it[deviceId] ?: emptyList() }
        }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    val audioDevices: StateFlow<List<AudioDeviceInfo>> = deviceManager.selectedDeviceId
        .flatMapLatest { deviceId ->
            remotePlaybackFeature.audioDevicesByDevice.map { it[deviceId] ?: emptyList() }
        }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    val actions: StateFlow<List<ActionInfo>> = deviceManager.selectedDeviceId
        .flatMapLatest { deviceId ->
            actionFeature.actionsByDevice.map { it[deviceId] ?: emptyList() }
        }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    val showActionLabels: StateFlow<Boolean> = preferencesRepository
        .readShowActionLabels()
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), true)

    fun onPlayPause(session: PlaybackInfo) = sendMessageToSelectedDevice(
        MediaAction(if (session.isPlaying) MediaActionType.Pause else MediaActionType.Play, session.source)
    )

    fun onNext(session: PlaybackInfo) = sendMessageToSelectedDevice(
        MediaAction(MediaActionType.Next, session.source)
    )

    fun onPrevious(session: PlaybackInfo) = sendMessageToSelectedDevice(
        MediaAction(MediaActionType.Previous, session.source)
    )

    fun onSeek(session: PlaybackInfo, position: Double) = sendMessageToSelectedDevice(
        MediaAction(MediaActionType.Seek, session.source, position)
    )

    fun onVolumeChange(device: AudioDeviceInfo, volume: Float) {
        sendMessageToSelectedDevice(AudioAction(AudioActionType.VolumeUpdate, device.deviceId, volume.toDouble()))
    }

    fun toggleMute(device: AudioDeviceInfo) {
        sendMessageToSelectedDevice(AudioAction(AudioActionType.ToggleMute, device.deviceId))
    }

    fun setDefaultDevice(device: AudioDeviceInfo) {
        sendMessageToSelectedDevice(AudioAction(AudioActionType.DefaultDevice, device.deviceId))
    }

    fun sendMessageToSelectedDevice(message: SocketMessage) {
        deviceManager.selectedDeviceId.value?.let { deviceId ->
            networkManager.sendMessage(deviceId, message)
        }
    }
}
