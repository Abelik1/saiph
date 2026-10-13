// SPDX-License-Identifier: GPL-3.0-only
package sefirah.network.orion

import android.content.Context
import android.content.Intent

/**
 * The owner's "pause Saiph" switch (home-screen widget and Settings). While paused, no
 * Link or Hosted service runs and nothing syncs; pairing, keys and settings are kept.
 */
object OrionPause {
    private const val KEY = "paused"
    /** Widgets and other views refresh on this explicit, app-internal broadcast. */
    const val CHANGED = "com.orionmini.mobile.SAIPH_STATE_CHANGED"
    const val WIDGET_RECEIVER = "com.orionmini.mobile.SaiphWidgetRefresh"

    fun paused(context: Context) = context.getSharedPreferences("orion", Context.MODE_PRIVATE).getBoolean(KEY, false)

    fun set(context: Context, paused: Boolean) {
        context.getSharedPreferences("orion", Context.MODE_PRIVATE).edit().putBoolean(KEY, paused).commit()
        changed(context)
    }

    fun changed(context: Context) {
        context.sendBroadcast(Intent(CHANGED).setClassName(context.packageName, WIDGET_RECEIVER))
    }
}
