package com.orionmini.mobile

import android.app.PendingIntent
import android.content.Intent
import android.os.Build
import android.service.quicksettings.Tile
import android.service.quicksettings.TileService
import dagger.hilt.android.AndroidEntryPoint
import sefirah.network.orion.OrionLink
import javax.inject.Inject

@AndroidEntryPoint
class OrionTileService : TileService() {
    @Inject lateinit var link: OrionLink
    override fun onStartListening() {
        qsTile?.apply { label = "Saiph"; state = if (link.status.value == "Online") Tile.STATE_ACTIVE else Tile.STATE_INACTIVE; updateTile() }
    }
    @Suppress("DEPRECATION")
    @android.annotation.SuppressLint("StartActivityAndCollapseDeprecated") // Intent overload required below API 34.
    override fun onClick() {
        val intent = Intent(this, OrionActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        if (Build.VERSION.SDK_INT >= 34) startActivityAndCollapse(PendingIntent.getActivity(this, 0, intent, PendingIntent.FLAG_IMMUTABLE))
        else startActivityAndCollapse(intent)
    }
}
