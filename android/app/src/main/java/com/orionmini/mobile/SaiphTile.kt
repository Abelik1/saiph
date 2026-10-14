// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.os.Build
import android.service.quicksettings.Tile
import android.service.quicksettings.TileService

/**
 * Quick Settings tile: Saiph on (active) or paused (inactive), toggled with one tap.
 * On a locked phone the tap asks for an unlock first, like Saiph's own app lock.
 */
class SaiphTile : TileService() {
    override fun onStartListening() = update()

    override fun onClick() {
        if (isLocked) unlockAndRun { toggle() } else toggle()
    }

    private fun toggle() {
        SaiphControls.toggle(this)
        update()
    }

    private fun update() {
        val tile = qsTile ?: return
        val state = SaiphControls.state(this)
        tile.label = "Saiph"
        tile.state = if (state == SaiphControls.State.PAUSED) Tile.STATE_INACTIVE else Tile.STATE_ACTIVE
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) tile.subtitle = SaiphControls.short(state)
        tile.contentDescription = "Saiph, " + SaiphControls.short(state)
        tile.updateTile()
    }
}
