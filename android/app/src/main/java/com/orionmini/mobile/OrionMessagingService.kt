package com.orionmini.mobile

import sefirah.network.orion.Api
import com.castle.sefirah.BuildConfig

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.ActivityCompat
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import kotlin.concurrent.thread

/**
 * Inbox items arrive as data-only messages, so this app draws each notification itself,
 * tagged with the item id. When the item is decided on another device the hub sends the
 * new status and the notification here is withdrawn.
 */
object Notify {
    const val ID = 1
    private const val CHANNEL = "orion_inbox"

    private fun channel(context: Context) = context.getSystemService(NotificationManager::class.java)
        .createNotificationChannel(NotificationChannel(CHANNEL, "Saiph", NotificationManager.IMPORTANCE_HIGH))

    private fun allowed(context: Context) =
        Build.VERSION.SDK_INT < 33 || ActivityCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED

    private fun decision(context: Context, id: String, decision: String, label: String): NotificationCompat.Action {
        val intent = Intent(context, DecisionReceiver::class.java).putExtra("id", id).putExtra("decision", decision)
        val pending = PendingIntent.getBroadcast(context, (id + decision).hashCode(), intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        return NotificationCompat.Action.Builder(0, label, pending).build()
    }

    fun show(context: Context, id: String?, kind: String, title: String, body: String, phoneAction: Boolean = false) {
        channel(context)
        if (!allowed(context)) return
        val open = PendingIntent.getActivity(context, 0, Intent(context, OrionActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP), PendingIntent.FLAG_IMMUTABLE)
        val builder = NotificationCompat.Builder(context, CHANNEL).setSmallIcon(android.R.drawable.ic_popup_reminder)
            .setContentTitle(title).setContentText(body).setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setContentIntent(open).setAutoCancel(true)
        if (id != null && phoneAction) {
            // Full recipient/action/text is reviewed in the signed inbox screen.
            builder.addAction(NotificationCompat.Action.Builder(0,"Review",open).build())
                .addAction(decision(context,id,"dismiss","Dismiss"))
        } else if (id != null && kind == "proposal") {
            builder.addAction(decision(context, id, "accept", "Add to calendar")).addAction(decision(context, id, "dismiss", "Dismiss"))
        } else if (id != null) {
            builder.addAction(decision(context, id, "done", "Clear"))
        }
        try { NotificationManagerCompat.from(context).notify(id ?: System.currentTimeMillis().toString(), ID, builder.build()) }
        catch (_: SecurityException) { /* Permission can be revoked between check and delivery. */ }
    }

    fun withdraw(context: Context, id: String) = NotificationManagerCompat.from(context).cancel(id, ID)
}

class OrionMessagingService : FirebaseMessagingService() {
    @Deprecated("Firebase still calls this for token refreshes.")
    override fun onNewToken(token: String) {
        if (BuildConfig.HAS_FIREBASE_PUSH) thread { runCatching { Api.registerPush(this, token) } }
    }

    override fun onMessageReceived(message: RemoteMessage) {
        if (!BuildConfig.HAS_FIREBASE_PUSH) return
        val data = message.data
        if (data["type"] == "inbox") {
            val id = data["id"] ?: return
            if (data["status"] == "new") Notify.show(this, id, data["kind"] ?: "notice", data["title"] ?: "Saiph", data["body"] ?: "",data["proposal_type"]=="phone_action")
            else Notify.withdraw(this, id)
            return
        }
        // Older hub messages (a task is due, an automation finished) carry their own text.
        Notify.show(this, null, "notice", message.notification?.title ?: "Saiph", message.notification?.body ?: data["body"] ?: "New update")
    }
}

/** Add to calendar / Dismiss / Clear straight from the notification. */
class DecisionReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val id = intent.getStringExtra("id") ?: return
        val decision = intent.getStringExtra("decision") ?: return
        if (decision !in setOf("accept", "dismiss", "done")) return
        context.getSharedPreferences("orion_decisions", Context.MODE_PRIVATE).edit().putString(id, decision).commit()
        val done = goAsync()
        thread {
            try { CompanionSync.flushDecisions(context) } finally { done.finish() }
        }
    }
}
