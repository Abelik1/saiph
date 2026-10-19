// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

/** Decide before launching Android UI; a repeated denied request must never be a dead button. */
internal object HostedSharing {
    enum class Route { REQUEST, SETTINGS }
    fun route(allGranted: Boolean, selectedPhotos: Boolean, previouslyRequested: Boolean, canAskAgain: Boolean) =
        if (allGranted || (!selectedPhotos && previouslyRequested && !canAskAgain)) Route.SETTINGS else Route.REQUEST
    fun needsSetup(approved: Boolean, completed: Boolean) = approved && !completed
}
