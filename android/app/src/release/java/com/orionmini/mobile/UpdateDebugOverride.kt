// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.content.Context
import android.view.View

/** Release builds cannot redirect the updater: the debug test server exists only in src/debug. */
object UpdateDebugOverride {
    @Suppress("UNUSED_PARAMETER") fun source(context: Context): UpdateSource? = null
    @Suppress("UNUSED_PARAMETER") fun controls(context: Context): List<View> = emptyList()
}
