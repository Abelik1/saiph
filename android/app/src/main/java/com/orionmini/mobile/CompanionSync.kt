package com.orionmini.mobile

import android.content.Context
import android.app.NotificationManager
import com.castle.sefirah.BuildConfig
import com.google.firebase.messaging.FirebaseMessaging
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import sefirah.network.orion.Api
import sefirah.network.orion.OrionCompanion
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class CompanionSync @Inject constructor(private val context: Context) : OrionCompanion {
    private val pushRegistration = PushRegistrationGate()
    override suspend fun refresh() = withContext(Dispatchers.IO) {
        flushDecisions(context)
        val paired = context.getSharedPreferences("orion", Context.MODE_PRIVATE).contains("device_id")
        if (BuildConfig.HAS_FIREBASE_PUSH && paired && pushRegistration.begin(android.os.SystemClock.elapsedRealtime())) {
            runCatching {
                FirebaseMessaging.getInstance().token.addOnSuccessListener { token ->
                    kotlin.concurrent.thread {
                        // Api resolves only the saved, validated paired Hub; no owner fallback.
                        pushRegistration.finished(runCatching { Api.registerPush(context, token) }.isSuccess)
                    }
                }.addOnFailureListener { pushRegistration.finished(false) }
            }.onFailure { pushRegistration.finished(false) }
        }
        val items = Api.inbox(context)
        val seen = context.getSharedPreferences("orion_inbox_seen", Context.MODE_PRIVATE)
        val shade = context.getSystemService(NotificationManager::class.java)
        for (index in 0 until items.length()) {
            val item = items.getJSONObject(index); val id = item.getString("id")
            if (item.getString("status") != "new") { Notify.withdraw(context, id); continue }
            if (!seen.getBoolean(id, false)) {
                val phoneAction=item.optJSONObject("proposal")?.has("action")==true
                Notify.show(context, id, item.getString("kind"), if(phoneAction) "Phone action needs your approval" else item.getString("title"), if(phoneAction) "Open Saiph to review it" else item.optString("body"), phoneAction)
                // Do not mark delivered while Android notifications are disabled.
                if (shade.areNotificationsEnabled()) seen.edit().putBoolean(id, true).apply()
            }
        }
    }
    /** Notify about a newer Hub build; downloading and installing wait for the person (UpdateActivity). */
    override suspend fun checkUpdate() = withContext(Dispatchers.IO) { UpdateNotices.checkQuietly(context) }
    companion object {
        @Synchronized fun flushDecisions(context: Context) {
            val pending = context.getSharedPreferences("orion_decisions", Context.MODE_PRIVATE)
            pending.all.toMap().forEach { (id, value) ->
                runCatching { Api.decide(context, id, value as String) }.onSuccess {
                    pending.edit().remove(id).commit(); Notify.withdraw(context, id)
                }
            }
        }
    }
}
