// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

/** Fractional sensor-frame selection; never build a queue of overdue captures. */
internal class CameraCadence(fps: Int) {
    private val period = 1_000_000_000L / fps.also { require(it in setOf(15, 20, 30)) }
    private var next: Long? = null
    fun take(now: Long): Boolean {
        val due = next
        if (due != null && now < due) return false
        next = if (due == null) now + period else maxOf(due + period, now)
        return true
    }
}
