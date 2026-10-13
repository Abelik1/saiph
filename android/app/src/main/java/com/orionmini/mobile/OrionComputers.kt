// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.content.Context
import kotlinx.serialization.json.JsonObject
import org.json.JSONObject
import sefirah.network.orion.Api
import sefirah.network.orion.OrionLink
import sefirah.network.orion.OrionRemote

/** Another paired device as the Hub reports it; battery is null when the device has none. */
data class LinkDevice(val id: String, val name: String, val online: Boolean, val capabilities: Set<String>,
                      val battery: Int?, val charging: Boolean) {
    // Computers offer handoff; phones advertise their battery capability instead.
    val computer get() = "handoff" in capabilities
}

object OrionComputers {
    /** Other paired devices. Call off the main thread. */
    fun devices(context: Context): List<LinkDevice> {
        val own = context.getSharedPreferences("orion", 0).getString("device_id", null)
        val devices = JSONObject(Api.request(context, "/v1/link/phone")).getJSONArray("devices")
        return (0 until devices.length()).map(devices::getJSONObject).filter { it.getString("id") != own }.map { device ->
            val caps = device.optJSONArray("capabilities")
            val battery = device.optJSONObject("battery")
            LinkDevice(device.getString("id"), device.getString("name"), device.optBoolean("online"),
                caps?.let { c -> (0 until c.length()).map(c::optString).toSet() }.orEmpty(),
                battery?.optInt("battery_level", -1)?.takeIf { it in 0..100 }, battery?.optBoolean("is_charging") == true)
        }
    }

    /** Paired computers that currently offer phone remote control. Call off the main thread. */
    fun remote(context: Context): List<Pair<String, String>> =
        devices(context).filter { it.online && "remote" in it.capabilities }.map { it.id to it.name }

    /** Lock uses the remote's opt-in "This computer" control; the computer refuses it unless allowed. */
    fun lock(link: OrionLink, computer: String) =
        link.status.value == "Online" && link.publish("remote.command", OrionRemote.command("system", "lock"), computer)

    /** Find this computer: it plays a sound with a Stop window, if its owner allows it. */
    fun ring(link: OrionLink, computer: String) =
        link.status.value == "Online" && link.publish("computer.ring", JsonObject(emptyMap()), computer)

    fun summary(device: LinkDevice) = device.name + when {
        !device.online -> " · offline"
        device.battery != null -> " · ${device.battery}%" + if (device.charging) " · charging" else ""
        else -> ""
    }
}
