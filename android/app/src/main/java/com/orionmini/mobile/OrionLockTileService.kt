// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.app.PendingIntent
import android.content.Intent
import android.os.Build
import android.service.quicksettings.Tile
import android.service.quicksettings.TileService
import android.widget.Toast
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.*
import sefirah.network.orion.OrionLink
import javax.inject.Inject

/** Quick-settings "Lock computer": locks the one computer that allows it, or opens the remote to choose. */
@AndroidEntryPoint
class OrionLockTileService : TileService() {
    @Inject lateinit var link: OrionLink
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    override fun onStartListening() {
        qsTile?.apply { label = "Lock computer"; state = if (link.status.value == "Online") Tile.STATE_INACTIVE else Tile.STATE_UNAVAILABLE; updateTile() }
    }
    override fun onClick() {
        scope.launch {
            val computers = withContext(Dispatchers.IO) { runCatching { OrionComputers.remote(this@OrionLockTileService) }.getOrNull() }
            when {
                computers.isNullOrEmpty() -> Toast.makeText(this@OrionLockTileService, "No computer allows locking from this phone. Turn it on in Saiph's Phone remote settings.", Toast.LENGTH_LONG).show()
                computers.size == 1 -> Toast.makeText(this@OrionLockTileService,
                    if (OrionComputers.lock(link, computers.single().first)) "Locking ${computers.single().second}…" else "Saiph is reconnecting. Nothing was sent.", Toast.LENGTH_SHORT).show()
                else -> open()
            }
        }
    }
    @Suppress("DEPRECATION")
    @android.annotation.SuppressLint("StartActivityAndCollapseDeprecated") // Intent overload required below API 34.
    private fun open() {
        val intent = Intent(this, OrionRemoteActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        if (Build.VERSION.SDK_INT >= 34) startActivityAndCollapse(PendingIntent.getActivity(this, 1, intent, PendingIntent.FLAG_IMMUTABLE))
        else startActivityAndCollapse(intent)
    }
    override fun onDestroy() { scope.cancel(); super.onDestroy() }
}
