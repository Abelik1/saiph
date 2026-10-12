package sefirah.communication.call

import android.annotation.SuppressLint
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.telephony.TelephonyManager
import android.util.Log
import androidx.core.content.ContextCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import sefirah.common.util.phoneStatePermissionGranted
import sefirah.communication.utils.ContactsHelper
import sefirah.BoundFeature
import sefirah.domain.interfaces.DeviceManager
import sefirah.domain.interfaces.NetworkManager
import sefirah.domain.model.CallInfo
import sefirah.domain.model.CallState
import sefirah.domain.model.DevicePreferences
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class CallStateFeature @Inject constructor(
    private val context: Context,
    deviceManager: DeviceManager,
    private val networkManager: NetworkManager,
) : BoundFeature(deviceManager) {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var isRegistered = false
    private val contactHelper = ContactsHelper()

    /** Last state we sent per phone number, to avoid duplicate events. */
    private val lastStateByNumber = mutableMapOf<String, Int>()

    private val phoneReceiver = object : BroadcastReceiver() {
        @SuppressLint("MissingPermission")
        override fun onReceive(receiverContext: Context, intent: Intent?) {
            if(!hasPermissions())return
            if (intent?.action != TelephonyManager.ACTION_PHONE_STATE_CHANGED) return

            val stateStr = intent.getStringExtra(TelephonyManager.EXTRA_STATE) ?: return
            val state = when (stateStr) {
                TelephonyManager.EXTRA_STATE_RINGING -> TelephonyManager.CALL_STATE_RINGING
                TelephonyManager.EXTRA_STATE_OFFHOOK -> TelephonyManager.CALL_STATE_OFFHOOK
                else -> TelephonyManager.CALL_STATE_IDLE
            }

            // Caller number is optional without call-log permission. State still matters.
            val phoneNumber = intent.getStringExtra(TelephonyManager.EXTRA_INCOMING_NUMBER)
                ?: lastStateByNumber.keys.firstOrNull().orEmpty()
            if(state==TelephonyManager.CALL_STATE_IDLE) {
                lastStateByNumber.keys.toList().forEach { onPhoneStateChanged(receiverContext.applicationContext,state,it) }
                return
            }
            if(phoneNumber.isNotEmpty())lastStateByNumber.remove("")
            onPhoneStateChanged(receiverContext.applicationContext, state, phoneNumber)
        }
    }

    override fun isPrefEnabled(prefs: DevicePreferences) = prefs.callStateSync

    override fun hasPermissions(): Boolean = phoneStatePermissionGranted(context)

    override suspend fun onStart() {
        registerReceiver()
    }

    override suspend fun onStop() {
        unregisterReceiver()
    }

    private fun registerReceiver() {
        if (isRegistered) return
        ContextCompat.registerReceiver(
            context,
            phoneReceiver,
            IntentFilter(TelephonyManager.ACTION_PHONE_STATE_CHANGED),
            ContextCompat.RECEIVER_NOT_EXPORTED
        )
        isRegistered = true
    }

    private fun unregisterReceiver() {
        if (!isRegistered) return
        try {
            context.unregisterReceiver(phoneReceiver)
        } catch (e: Exception) {
            Log.w(TAG, "Error unregistering call state receiver", e)
        }
        isRegistered = false
        lastStateByNumber.clear()
    }

    private fun onPhoneStateChanged(context: Context, state: Int, phoneNumber: String) {
        val contactInfo = runCatching { contactHelper.getContactInfo(context, phoneNumber) }.getOrNull()
        when (state) {
            TelephonyManager.CALL_STATE_RINGING -> {
                if (state != lastStateByNumber[phoneNumber]) {
                    lastStateByNumber[phoneNumber] = state
                    sendToDevices(CallInfo(CallState.Ringing, phoneNumber, contactInfo))
                }
            }
            TelephonyManager.CALL_STATE_OFFHOOK -> {
                if (lastStateByNumber.containsKey(phoneNumber) && state != lastStateByNumber[phoneNumber]) {
                    lastStateByNumber[phoneNumber] = state
                    sendToDevices(CallInfo(CallState.InProgress, phoneNumber, contactInfo))
                }
            }
            TelephonyManager.CALL_STATE_IDLE -> {
                val previousState = lastStateByNumber.remove(phoneNumber)
                if (previousState == TelephonyManager.CALL_STATE_RINGING) {
                    sendToDevices(CallInfo(CallState.MissedCall, phoneNumber, contactInfo))
                } else if (previousState != null) {
                    sendToDevices(CallInfo(CallState.Ended, phoneNumber, contactInfo))
                }
            }
        }
    }

    private fun sendToDevices(callInfo: CallInfo) {
        scope.launch {
            activeDeviceIds.forEach { deviceId ->
                networkManager.sendMessage(deviceId, callInfo)
            }
            Log.d(TAG, "Call state changed")
        }
    }

    companion object {
        private const val TAG = "CallStateFeature"
    }
}
