package sefirah.notification

import android.app.Notification
import android.app.PendingIntent
import android.app.RemoteInput
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.drawable.BitmapDrawable
import android.os.Build
import android.os.Bundle
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import android.text.SpannableString
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.os.bundleOf
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import sefirah.Feature
import sefirah.domain.model.DevicePreferences
import sefirah.domain.model.NotificationTextMessage
import sefirah.domain.model.NotificationAction
import sefirah.domain.model.NotificationInfo
import sefirah.domain.model.NotificationInfoType
import sefirah.domain.model.NotificationReply
import sefirah.domain.interfaces.DeviceManager
import sefirah.domain.interfaces.NetworkManager
import sefirah.domain.interfaces.NotificationCallback
import sefirah.common.util.bitmapToBase64
import sefirah.common.util.drawableToBase64
import sefirah.common.util.drawableToBitmap
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class NotificationFeature @Inject constructor(
    private val context: Context,
    deviceManager: DeviceManager,
    private val networkManager: NetworkManager,
) : Feature(deviceManager), NotificationCallback {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    @Volatile private var isListenerConnected : Boolean = false

    private lateinit var listener: NotificationListenerService
    fun isAvailable(): Boolean = isListenerConnected && ::listener.isInitialized &&
        NotificationManagerCompat.getEnabledListenerPackages(context).contains(context.packageName)
    private fun activeNotifications(): Array<out StatusBarNotification> = if(isAvailable()) try {
        listener.activeNotifications.orEmpty()
    } catch (_: SecurityException) { emptyArray() } else emptyArray()

    override fun isPrefEnabled(prefs: DevicePreferences) = prefs.notificationSync

    override suspend fun onStart(deviceId: String) {
        sendActiveNotifications(deviceId)
    }

    fun sendActiveNotifications(deviceId: String? = null) {
        val targetDeviceIds = deviceId?.let { setOf(it) } ?: enabledDevices

        if (!isAvailable() || targetDeviceIds.isEmpty()) {
            return
        } else {
            scope.launch {
                if (!isAvailable()) return@launch

                val activeNotifications = activeNotifications()
                if ("" in targetDeviceIds) networkManager.reconcileNotifications(
                    activeNotifications.orEmpty().filter { it.packageName != context.packageName }.take(500).map { it.key })
                if (!activeNotifications.isNullOrEmpty()) {
                    activeNotifications.forEach { sbn ->
                        sendNotification(sbn, NotificationInfoType.Active, targetDeviceIds)
                    }
                }
            }
        }
    }

    fun removeAllNotification() {
        if (isAvailable()) listener.cancelAllNotifications()
    }

    fun removeNotification(notificationId: String?) {
        if (isAvailable()) listener.cancelNotification(notificationId)
    }


    override fun onNotificationPosted(notification: StatusBarNotification) {
        sendNotification(notification, NotificationInfoType.New, enabledDevices)
    }

    override fun onNotificationRemoved(notification: StatusBarNotification) {
        if(!isAvailable())return
        // to remove the notification on the desktop
        val removeNotificationMessage = NotificationInfo(
            appPackage = notification.packageName,
            notificationKey = notification.key,
            infoType = NotificationInfoType.Removed,
            tag = notification.tag,
        )
        enabledDevices.forEach { deviceId ->
            networkManager.sendMessage(deviceId, removeNotificationMessage)
        }
    }

    override fun onListenerConnected(service: NotificationListenerService) {
        isListenerConnected = true
        listener = service
        networkManager.refreshCapabilities()
        sendActiveNotifications()
    }

    override fun onListenerDisconnected() {
        isListenerConnected = false
        networkManager.refreshCapabilities()
    }

    fun performNotificationAction(action: NotificationAction) {
        if (!isAvailable()) return
        val activeNotification = activeNotifications().find {
            it.key == action.notificationKey
        } ?: return

        val actions = activeNotification.notification.actions ?: return
        val clickAction = actions.getOrNull(action.actionIndex) ?: return

        try {
            clickAction.actionIntent.send()
        } catch (e: PendingIntent.CanceledException) {
            Log.w(TAG, "Notification action unavailable")
        }
    }

    fun openNotification(notificationKey: String?) {
        if (!isAvailable()) return
        val notification = activeNotifications()
            .find { it.key == notificationKey }
            ?.notification ?: return

        val contentIntent = notification.contentIntent ?: return
        
        try {
            contentIntent.send()
        } catch (e: PendingIntent.CanceledException) {
            Log.w(TAG, "Notification open unavailable")
        }
    }

    fun performReplyAction(action: NotificationReply) {
        if (!isAvailable()) return
        // Get notification and its first reply action (usually messaging apps only have one)
        val notification = activeNotifications()
            .find { it.key == action.notificationKey }
            ?.notification ?: return

        // Most messaging apps put the reply action as the first action with RemoteInput
        val replyAction = notification.actions?.firstOrNull { 
            it.remoteInputs?.isNotEmpty() == true 
        } ?: return
        if (replyAction.remoteInputs.none { it.resultKey == action.replyResultKey }) return

        try {
            Intent().apply {
                RemoteInput.addResultsToIntent(
                    replyAction.remoteInputs,
                    this,
                    bundleOf(action.replyResultKey to action.replyText)
                )
            }.also { replyAction.actionIntent.send(listener, 0, it) }

        } catch (e: PendingIntent.CanceledException) {
            Log.w(TAG, "Notification reply unavailable")
        }
    }

    private fun sendNotification(sbn: StatusBarNotification, notificationInfoType: NotificationInfoType, targetDeviceIds: Set<String>) {
        if (targetDeviceIds.isEmpty() || !isAvailable()) return
        val notification = sbn.notification
        val packageName = sbn.packageName

        // Get the app name using PackageManager
        val packageManager = listener.packageManager

        val appName = try {
            val applicationInfo = packageManager.getApplicationInfo(packageName, 0)
            packageManager.getApplicationLabel(applicationInfo).toString()
        } catch (e: PackageManager.NameNotFoundException) {
            Log.e(TAG, "Couldn't resolve name $packageName", e)
            return
        }

        if ((notification.flags and Notification.FLAG_ONGOING_EVENT) != 0
            || (notification.flags and Notification.FLAG_FOREGROUND_SERVICE) != 0
            || (notification.flags and Notification.FLAG_LOCAL_ONLY) != 0
            || (notification.flags and NotificationCompat.FLAG_GROUP_SUMMARY) != 0
            || notification.isMediaStyle()) {
            return
        }

        if ("com.facebook.orca" == packageName &&
            (sbn.id == 10012) &&
            "Messenger" == appName && notification.tickerText == null
        ) {
            //HACK: Hide weird Facebook empty "Messenger" notification that is actually not shown in the phone
            return
        }

        if ("com.android.systemui" == packageName) {
            if ("low_battery" == sbn.tag) {
                //HACK: Android low battery notification are posted again every few seconds. Ignore them, as we already have a battery indicator.
                return
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                if ("MediaOngoingActivity" == notification.channelId) {
                    //HACK: Samsung OneUI sends this notification when media playback is started.
                    return
                }
            }
        }

        if (context.packageName == packageName) {
            // Don't send our own notifications
            return
        }

        scope.launch {
            if(!isAvailable())return@launch
            // Get app icon
            val appIcon = try {
                val appIconDrawable = packageManager.getApplicationIcon(packageName)
                if (appIconDrawable is BitmapDrawable) {
                    val appIconBitmap = appIconDrawable.bitmap
                    bitmapToBase64(appIconBitmap)
                } else {
                    // Convert to Bitmap if it's not already a BitmapDrawable
                    val appIconBitmap = drawableToBitmap(appIconDrawable)
                    bitmapToBase64(appIconBitmap)
                }
            } catch (e: Exception) {
                // Icons are optional; exception bodies never enter logs.
                null
            }

            val notificationKey = sbn.key

            // Get the notification large icon
            val largeIcon = notification.getLargeIcon()?.let { icon ->
                icon.loadDrawable(context)?.let { drawableToBase64(it) }
            }

            // Get picture (if available)
//            val picture = notification.extras.get(Notification.EXTRA_PICTURE)?.let { pictureBitmap ->
//                bitmapToBase64(pictureBitmap as Bitmap)
//            }

            // Use the utility function to get text from SpannableString
            val title = getSpannableText(notification.extras.getCharSequence(Notification.EXTRA_TITLE))
                ?: getSpannableText(notification.extras.getCharSequence(Notification.EXTRA_TITLE_BIG))

            if (title.isNullOrEmpty()) return@launch

            val text = getSpannableText(notification.extras.getCharSequence(Notification.EXTRA_TEXT))
                ?: getSpannableText(notification.extras.getCharSequence(Notification.EXTRA_BIG_TEXT))
                ?: getSpannableText(notification.extras.getCharSequence(Notification.EXTRA_SUB_TEXT))

            val messages = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
                notification.extras.getParcelableArray(Notification.EXTRA_MESSAGES)?.mapNotNull {
                    val bundle = it as? Bundle
                    val sender = bundle?.getCharSequence("sender")?.toString() // Get the sender's name
                    val messageText = bundle?.getCharSequence("text")?.toString()

                    if (sender != null && messageText != null) {
                        NotificationTextMessage(sender = sender, text = messageText)
                    } else {
                        null
                    }
                } ?: emptyList()
            } else {
                emptyList()
            }

            val actions = notification.actions?.mapIndexedNotNull { index, action ->
                // skip reply actions
                if (!action.remoteInputs?.firstOrNull()?.resultKey.isNullOrEmpty()) return@mapIndexedNotNull null

                NotificationAction(
                    notificationKey = sbn.key,
                    label = action.title.toString(),
                    actionIndex = index
                )
            } ?: emptyList()

            val replyResultKey = notification.actions?.firstNotNullOfOrNull { action ->
                action.remoteInputs?.firstOrNull()?.resultKey
            }

            val notificationInfo = NotificationInfo(
                notificationKey = notificationKey,
                infoType = notificationInfoType,
                timestampMillis = notification.`when`,
                appPackage = sbn.packageName,
                appName = appName,
                title = title,
                text = text,
                messages = messages,
                groupKey = sbn.groupKey,
                tag = sbn.tag,
                replyResultKey = replyResultKey,
                appIcon = appIcon,
                largeIcon = largeIcon,
                actions = actions
            )

            try {
                targetDeviceIds.forEach { deviceId ->
                    networkManager.sendMessage(deviceId, notificationInfo)
                }
            } catch (e: Exception) {
                Log.w(TAG, "Notification delivery unavailable")
            }
        }
    }

    private fun getSpannableText(charSequence: CharSequence?): String? {
        return when (charSequence) {
            is SpannableString -> charSequence.toString()
            else -> charSequence?.toString()
        }
    }

    private fun Notification.isMediaStyle(): Boolean {
        return $$"android.app.Notification$MediaStyle" == this.extras.getString(Notification.EXTRA_TEMPLATE)
    }

    companion object {
        const val TAG = "NotificationFeature"
    }
}
