// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.BroadcastReceiver
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.service.quicksettings.TileService
import android.view.View
import android.widget.RemoteViews
import android.widget.Toast
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

/** Shared by the widgets and the Quick Settings tile, so every control behaves the same. */
object SaiphControls {
    const val TOGGLE = "com.orionmini.mobile.SAIPH_TOGGLE"
    const val RING = "com.orionmini.mobile.SAIPH_RING_COMPUTER"
    const val EXTRA_COMPUTER = "computer"

    enum class State { PAUSED, HOSTED, NOT_SET_UP, CONNECTED, RECONNECTING }

    fun state(context: Context): State {
        if (OrionPause.paused(context)) return State.PAUSED
        if (context.getSharedPreferences("orion_hosted", 0).getBoolean("enabled", false)) return State.HOSTED
        if (!context.getSharedPreferences("orion", 0).contains("device_id")) return State.NOT_SET_UP
        val link = EntryPointAccessors.fromApplication(context, SaiphWidgetEntryPoint::class.java).link()
        return if (link.status.value == "Online") State.CONNECTED else State.RECONNECTING
    }

    /** One line for the wide widgets. */
    fun status(state: State) = when (state) {
        State.PAUSED -> "Paused · nothing syncs"
        State.HOSTED -> "On · Saiph Hosted"
        State.NOT_SET_UP -> "Not set up yet"
        State.CONNECTED -> "On · connected"
        State.RECONNECTING -> "On · reconnecting"
    }

    /** A computer name short enough for a half-width button: "Orion desktop (AlexMainDesktop)" -> "Orion desktop". */
    fun shortName(name: String): String {
        val plain = name.substringBefore(" (").trim().ifEmpty { name.trim() }
        return if (plain.length <= 16) plain else plain.take(15).trimEnd() + "…"
    }

    /** One or two words for the small widget and the tile's subtitle. */
    fun short(state: State) = when (state) {
        State.PAUSED -> "Paused"
        State.HOSTED, State.CONNECTED -> "Connected"
        State.NOT_SET_UP -> "Set up"
        State.RECONNECTING -> "Reconnecting"
    }

    fun toggle(context: Context) {
        val paused = !OrionPause.paused(context)
        OrionPause.set(context, paused)
        val network = EntryPointAccessors.fromApplication(context, SaiphWidgetEntryPoint::class.java).network()
        if (paused) network.stopService() else network.startService()
    }

    /** The toggle goes to a receiver other apps cannot reach; only Saiph's own controls send it. */
    fun togglePending(context: Context): PendingIntent = PendingIntent.getBroadcast(context, 0,
        Intent(context, SaiphWidgetRefresh::class.java).setAction(TOGGLE), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)

    fun ringPending(context: Context, computer: String): PendingIntent = PendingIntent.getBroadcast(context, 1,
        Intent(context, SaiphWidgetRefresh::class.java).setAction(RING).putExtra(EXTRA_COMPUTER, computer),
        PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)

    fun activityPending(context: Context, code: Int, target: Class<*>): PendingIntent = PendingIntent.getActivity(context, code,
        Intent(context, target).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)

    /** Redraws every Saiph widget and asks the system to refresh the tile. */
    fun refresh(context: Context) {
        SaiphWidget.render(context)
        SaiphToggleWidget.render(context)
        SaiphActionsWidget.render(context, null)
        SaiphActionsWidget.loadComputers(context)
        try { TileService.requestListeningState(context, ComponentName(context, SaiphTile::class.java)) } catch (_: RuntimeException) { }
    }
}

/** Home-screen widget: Saiph's state and a Pause / Resume button. */
class SaiphWidget : AppWidgetProvider() {
    override fun onUpdate(context: Context, manager: AppWidgetManager, ids: IntArray) = render(context)

    companion object {
        fun render(context: Context) {
            val manager = AppWidgetManager.getInstance(context)
            val ids = manager.getAppWidgetIds(ComponentName(context, SaiphWidget::class.java))
            if (ids.isEmpty()) return
            val state = SaiphControls.state(context)
            val views = RemoteViews(context.packageName, R.layout.saiph_widget).apply {
                setTextViewText(R.id.saiph_widget_status, SaiphControls.status(state))
                setTextViewText(R.id.saiph_widget_toggle, if (state == SaiphControls.State.PAUSED) "Resume" else "Pause")
                setOnClickPendingIntent(R.id.saiph_widget_toggle, SaiphControls.togglePending(context))
                setOnClickPendingIntent(R.id.saiph_widget_text, SaiphControls.activityPending(context, 0, OrionActivity::class.java))
            }
            manager.updateAppWidget(ids, views)
        }
    }
}

/** Smallest widget: one tap pauses or resumes Saiph. */
class SaiphToggleWidget : AppWidgetProvider() {
    override fun onUpdate(context: Context, manager: AppWidgetManager, ids: IntArray) = render(context)

    companion object {
        fun render(context: Context) {
            val manager = AppWidgetManager.getInstance(context)
            val ids = manager.getAppWidgetIds(ComponentName(context, SaiphToggleWidget::class.java))
            if (ids.isEmpty()) return
            val state = SaiphControls.state(context)
            val views = RemoteViews(context.packageName, R.layout.saiph_widget_toggle).apply {
                setTextViewText(R.id.saiph_toggle_state, SaiphControls.short(state))
                setInt(R.id.saiph_toggle_root, "setBackgroundResource",
                    if (state == SaiphControls.State.PAUSED) R.drawable.saiph_widget_background else R.drawable.saiph_widget_background_on)
                setOnClickPendingIntent(R.id.saiph_toggle_root, SaiphControls.togglePending(context))
            }
            manager.updateAppWidget(ids, views)
        }
    }
}

/** Larger widget: state, Pause / Resume, ring a computer and the phone-to-computer actions. */
class SaiphActionsWidget : AppWidgetProvider() {
    override fun onUpdate(context: Context, manager: AppWidgetManager, ids: IntArray) {
        render(context, null)
        loadComputers(context)
    }

    companion object {
        /** Reads the paired computers off the main thread, then redraws with their names and batteries. */
        fun loadComputers(context: Context) {
            val manager = AppWidgetManager.getInstance(context)
            if (manager.getAppWidgetIds(ComponentName(context, SaiphActionsWidget::class.java)).isEmpty()) return
            if (SaiphControls.state(context) != SaiphControls.State.CONNECTED) return
            val app = context.applicationContext
            Thread {
                val computers = try { OrionComputers.devices(app).filter { it.computer } } catch (_: Exception) { null }
                if (computers != null) render(app, computers)
            }.start()
        }

        fun render(context: Context, computers: List<LinkDevice>?) {
            val manager = AppWidgetManager.getInstance(context)
            val ids = manager.getAppWidgetIds(ComponentName(context, SaiphActionsWidget::class.java))
            if (ids.isEmpty()) return
            val state = SaiphControls.state(context)
            val connected = state == SaiphControls.State.CONNECTED
            // Ring the first online computer that allows it; the app lists every computer.
            val ringable = computers?.firstOrNull { it.online && "ring" in it.capabilities }
            val views = RemoteViews(context.packageName, R.layout.saiph_widget_actions).apply {
                setTextViewText(R.id.saiph_actions_status, SaiphControls.status(state))
                setTextViewText(R.id.saiph_actions_devices, computers?.joinToString("\n") { OrionComputers.summary(it) }.orEmpty())
                setViewVisibility(R.id.saiph_actions_devices, if (computers.isNullOrEmpty()) View.GONE else View.VISIBLE)
                setTextViewText(R.id.saiph_actions_toggle, if (state == SaiphControls.State.PAUSED) "Resume" else "Pause")
                setOnClickPendingIntent(R.id.saiph_actions_toggle, SaiphControls.togglePending(context))
                setOnClickPendingIntent(R.id.saiph_actions_header, SaiphControls.activityPending(context, 0, OrionActivity::class.java))
                setTextViewText(R.id.saiph_actions_ring, if (ringable != null) "Ring " + SaiphControls.shortName(ringable.name) else "Ring computer")
                if (ringable != null) setContentDescription(R.id.saiph_actions_ring, "Ring " + ringable.name)
                setBoolean(R.id.saiph_actions_ring, "setEnabled", connected && ringable != null)
                if (ringable != null) setOnClickPendingIntent(R.id.saiph_actions_ring, SaiphControls.ringPending(context, ringable.id))
                setBoolean(R.id.saiph_actions_photo, "setEnabled", connected)
                setBoolean(R.id.saiph_actions_sketch, "setEnabled", connected)
                setBoolean(R.id.saiph_actions_remote, "setEnabled", connected)
                setOnClickPendingIntent(R.id.saiph_actions_photo, SaiphControls.activityPending(context, 2, OrionCaptureActivity::class.java))
                setOnClickPendingIntent(R.id.saiph_actions_sketch, SaiphControls.activityPending(context, 3, OrionSketchActivity::class.java))
                setOnClickPendingIntent(R.id.saiph_actions_remote, SaiphControls.activityPending(context, 4, OrionRemoteActivity::class.java))
            }
            manager.updateAppWidget(ids, views)
        }
    }
}

/** Not exported: refreshes after state changes and handles taps from Saiph's own widgets. */
class SaiphWidgetRefresh : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        when (intent.action) {
            SaiphControls.TOGGLE -> SaiphControls.toggle(context)
            SaiphControls.RING -> {
                val computer = intent.getStringExtra(SaiphControls.EXTRA_COMPUTER)
                val link = EntryPointAccessors.fromApplication(context, SaiphWidgetEntryPoint::class.java).link()
                val sent = computer != null && OrionComputers.ring(link, computer)
                Toast.makeText(context, if (sent) "Ringing your computer…" else "Saiph is reconnecting. Nothing was sent.", Toast.LENGTH_SHORT).show()
            }
        }
        SaiphControls.refresh(context)
    }
}
