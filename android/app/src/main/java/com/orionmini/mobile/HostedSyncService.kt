// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.app.*
import android.content.Intent
import android.os.*
import androidx.core.app.NotificationCompat
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.*
import sefirah.clipboard.ClipboardFeature
import sefirah.domain.model.ClipboardInfo
import sefirah.network.orion.HostedFeatureBridge
import sefirah.network.orion.HostedPhoneBridge
import sefirah.notification.NotificationFeature
import javax.inject.Inject

/** Background preview; an absent/false setting exits before hooks or network. */
@AndroidEntryPoint
class HostedSyncService : Service() {
    @Inject lateinit var clipboard: ClipboardFeature
    @Inject lateinit var notifications: NotificationFeature
    @Inject lateinit var phone: HostedPhoneBridge
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var ownsHooks = false
    private var sender: ((String, kotlinx.serialization.json.JsonObject) -> Boolean)? = null
    private val runtime by lazy { HostedRuntime.get(this) }
    private val photos by lazy { HostedPhotos(this, runtime) }
    override fun onCreate() {
        super.onCreate()
        runtime.applyPackagedDefaults()
        if (!runtime.enabled()) { stopSelf(); return }
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel("orion_hosted", "Saiph Cloud preview", NotificationManager.IMPORTANCE_LOW))
        val open = PendingIntent.getActivity(this, 43, Intent(this, HostedActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        fun notice() = NotificationCompat.Builder(this, "orion_hosted").setSmallIcon(android.R.drawable.ic_menu_share)
            .setContentTitle("Saiph Cloud preview").setContentText(runtime.status).setContentIntent(open).setOngoing(true).setOnlyAlertOnce(true).build()
        startForeground(43, notice())
        ownsHooks = true
        sender = runtime::enqueue
        HostedFeatureBridge.publish = sender
        HostedFeatureBridge.publishPhone = runtime::enqueuePhone
        runtime.clipboard = { text -> Handler(Looper.getMainLooper()).post { if (runtime.enabled() && HostedAccount.get(this).signedIn()) clipboard.setClipboard(ClipboardInfo("text/plain", text)) } }
        runtime.dismiss = { key -> if (runtime.enabled() && notifications.isAvailable()) notifications.removeNotification(key) }
        // The runtime has checked the sender, the owner's switch and the permission.
        runtime.phone = { id, source, command ->
            if (command is sefirah.network.orion.HostedPhoneCommand.PhotoRequest)
                scope.launch { runCatching { runtime.sendPhoto(id, source, command.id) } }
            else phone.execute(id, source, runtime.label(source), command, { target, payload -> runtime.enqueuePhone(target, payload) {} },
                    { runtime.subscribers().keys })
        }
        scope.launch {
            notifications.enable(""); clipboard.enable("")
            var connected = false
            var listenerReady = false
            while (isActive && runtime.enabled()) {
                runCatching { runtime.step() }
                // Access may be granted while the transport is already connected.
                // Also reconcile after Android rebinds its listener.
                val ready = notifications.isAvailable()
                if (runtime.status == "Connected" && (!connected || ready && !listenerReady)) notifications.sendActiveNotifications("")
                listenerReady = ready
                connected = runtime.status == "Connected"
                runCatching { phone.refresh(runtime.textsAndCalls(), connected, runtime.subscribers().keys) }
                runCatching { photos.refresh(connected) }
                manager.notify(43, notice())
                // A ringing call is checked every two seconds; a text backlog continues shortly.
                withTimeoutOrNull(if (runtime.ringing) 2000L else if (runtime.textBacklog()) 1000L else 5000L) { runtime.wake.receive() }
            }
            stopSelf()
        }
    }
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int) = START_NOT_STICKY
    override fun onBind(intent: Intent?): IBinder? = null
    override fun onTimeout(startId: Int, fgsType: Int) { stopSelf() }
    override fun onDestroy() {
        scope.cancel()
        if (ownsHooks && HostedFeatureBridge.publish === sender) {
            HostedFeatureBridge.publish = null; HostedFeatureBridge.publishPhone = null
            runtime.clipboard = null; runtime.dismiss = null; runtime.phone = null
            runtime.invalidate()
            runBlocking(Dispatchers.IO) { withTimeoutOrNull(2000) { notifications.disable(""); clipboard.disable(""); phone.stop() } }
        }
        super.onDestroy()
    }
}
