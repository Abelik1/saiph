// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.content.Context
import org.json.JSONObject
import sefirah.network.orion.Api
import sefirah.network.orion.OrionLink
import sefirah.network.orion.OrionRemote

/** Paired computers that currently offer phone remote control. Call off the main thread. */
object OrionComputers {
    fun remote(context: Context): List<Pair<String, String>> {
        val own = context.getSharedPreferences("orion", 0).getString("device_id", null)
        val devices = JSONObject(Api.request(context, "/v1/link/phone")).getJSONArray("devices")
        return (0 until devices.length()).map(devices::getJSONObject).filter { device ->
            val caps = device.optJSONArray("capabilities")
            device.optBoolean("online") && device.getString("id") != own && caps != null && (0 until caps.length()).any { caps.optString(it) == "remote" }
        }.map { it.getString("id") to it.getString("name") }
    }

    /** Lock uses the remote's opt-in "This computer" control; the computer refuses it unless allowed. */
    fun lock(link: OrionLink, computer: String) =
        link.status.value == "Online" && link.publish("remote.command", OrionRemote.command("system", "lock"), computer)
}
