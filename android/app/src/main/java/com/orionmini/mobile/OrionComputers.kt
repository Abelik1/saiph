// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.content.Context
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
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

    /** A phone on a Saiph account rather than a Hub: the same commands go through Saiph Cloud. */
    fun cloud(context: Context) = !context.getSharedPreferences("orion", 0).contains("device_id")

    /** One command to one computer over whichever connection this phone uses; false when it was not sent. */
    fun send(context: Context, link: OrionLink?, computer: String, type: String, payload: JsonObject): Boolean =
        if (cloud(context)) HostedRuntime.get(context).enqueueRemote(computer, JsonObject(payload + ("type" to JsonPrimitive(type))))
        else link != null && link.status.value == "Online" && link.publish(type, payload, computer)

    /**
     * Computers to send to, as id and name. A Hub lists those online that offer [capability]; Saiph
     * Cloud lists the computers online now, and each one answers for its own settings. Off the main thread.
     */
    fun targets(context: Context, capability: String): List<Pair<String, String>> =
        if (cloud(context)) HostedRuntime.get(context).computers().toList()
        else devices(context).filter { it.online && it.computer && capability in it.capabilities }.map { it.id to it.name }

    /** Lock uses the remote's opt-in "This computer" control; the computer refuses it unless allowed. */
    fun lock(context: Context, link: OrionLink?, computer: String) =
        send(context, link, computer, "remote.command", OrionRemote.command("system", "lock"))

    /** Find this computer: it plays a sound with a Stop window, if its owner allows it. */
    fun ring(context: Context, link: OrionLink?, computer: String) =
        send(context, link, computer, "computer.ring", JsonObject(emptyMap()))

    /**
     * A photo or sketch onto a computer's clipboard, ready to paste. A Hub sends it to [computer];
     * Saiph Cloud shares it like a copied image, with every approved computer. Takes [file]; off the main thread.
     */
    suspend fun clipboardImage(context: Context, files: sefirah.network.orion.OrionDirectFiles, file: java.io.File, computer: String,
                               name: String, mime: String): Boolean {
        if (!cloud(context)) return files.capture(file, computer, name, mime)
        // Cloud takes images only from its own cache files.
        val staged = java.io.File(context.cacheDir, "orion-clipboard-" + java.util.UUID.randomUUID() + "." + (if (mime == "image/png") "png" else "jpg"))
        val ok = file.renameTo(staged) && HostedRuntime.get(context).enqueueClipboardImage(mime, staged)
        if (!ok) { file.delete(); staged.delete() }
        return ok
    }

    fun summary(device: LinkDevice) = device.name + when {
        !device.online -> " · offline"
        device.battery != null -> " · ${device.battery}%" + if (device.charging) " · charging" else ""
        else -> ""
    }
}
