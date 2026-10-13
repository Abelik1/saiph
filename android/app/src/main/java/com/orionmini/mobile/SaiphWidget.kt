// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.BroadcastReceiver
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.widget.RemoteViews
import com.castle.sefirah.R
import dagger.hilt.EntryPoint
import dagger.hilt.InstallIn
import dagger.hilt.android.EntryPointAccessors
import dagger.hilt.components.SingletonComponent
import sefirah.domain.interfaces.NetworkManager
import sefirah.network.orion.OrionLink
import sefirah.network.orion.OrionPause

@EntryPoint
@InstallIn(SingletonComponent::class)
interface SaiphWidgetEntryPoint {
    fun link(): OrionLink
    fun network(): NetworkManager
}

/** Home-screen widget: Saiph's state and a Pause / Resume button. */
class SaiphWidget : AppWidgetProvider() {
    override fun onUpdate(context: Context, manager: AppWidgetManager, ids: IntArray) = render(context)

    companion object {
        const val TOGGLE = "com.orionmini.mobile.SAIPH_TOGGLE"

        fun status(context: Context): String {
            if (OrionPause.paused(context)) return "Paused · nothing syncs"
            if (context.getSharedPreferences("orion_hosted", 0).getBoolean("enabled", false)) return "On · Saiph Hosted"
            if (!context.getSharedPreferences("orion", 0).contains("device_id")) return "Not set up yet"
            val link = EntryPointAccessors.fromApplication(context, SaiphWidgetEntryPoint::class.java).link()
            return if (link.status.value == "Online") "On · connected" else "On · reconnecting"
        }

        fun render(context: Context) {
            val manager = AppWidgetManager.getInstance(context)
            val ids = manager.getAppWidgetIds(ComponentName(context, SaiphWidget::class.java))
            if (ids.isEmpty()) return
            val paused = OrionPause.paused(context)
            // The toggle goes to a receiver other apps cannot reach; only this widget's own tap sends it.
            val toggle = PendingIntent.getBroadcast(context, 0, Intent(context, SaiphWidgetRefresh::class.java).setAction(TOGGLE),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            val open = PendingIntent.getActivity(context, 0, Intent(context, OrionActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            val views = RemoteViews(context.packageName, R.layout.saiph_widget).apply {
                setTextViewText(R.id.saiph_widget_status, status(context))
                setTextViewText(R.id.saiph_widget_toggle, if (paused) "Resume" else "Pause")
                setOnClickPendingIntent(R.id.saiph_widget_toggle, toggle)
                setOnClickPendingIntent(R.id.saiph_widget_text, open)
            }
            manager.updateAppWidget(ids, views)
        }
    }
}

/** Not exported: refreshes after state changes and handles the widget's own Pause / Resume tap. */
class SaiphWidgetRefresh : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == SaiphWidget.TOGGLE) {
            val paused = !OrionPause.paused(context)
            OrionPause.set(context, paused)
            val network = EntryPointAccessors.fromApplication(context, SaiphWidgetEntryPoint::class.java).network()
            if (paused) network.stopService() else network.startService()
        }
        SaiphWidget.render(context)
    }
}
