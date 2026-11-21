// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.content.Context
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonPrimitive
import org.json.JSONArray
import org.json.JSONObject
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress

/**
 * Wake a sleeping computer from a Saiph Cloud phone. No Hub stays awake on the network, so
 * while a computer is on it tells the phone its adapters' addresses (`computer.wake`), and
 * the phone sends the wake-on-LAN packet itself. That works on the same Wi-Fi, and only when
 * the computer's adapter allows waking.
 */
object CloudWake {
    data class Target(val id: String, val name: String, val addresses: List<String>)
    private val mac = Regex("[0-9a-f]{2}(:[0-9a-f]{2}){5}")
    private fun prefs(context: Context) = context.getSharedPreferences("orion_hosted_wake", 0)

    /** Exactly `type` and up to four addresses; anything else is ignored. */
    fun read(payload: JsonObject): List<String>? = runCatching {
        require(payload.keys == setOf("type", "addresses"))
        payload.getValue("addresses").jsonArray.map { it.jsonPrimitive.content }
            .also { list -> require(list.size in 1..4 && list.all(mac::matches)) }
    }.getOrNull()

    fun remember(context: Context, computer: String, name: String, payload: JsonObject) {
        val addresses = read(payload) ?: return
        val all = runCatching { JSONObject(prefs(context).getString("targets", "{}")!!) }.getOrDefault(JSONObject())
        all.put(computer, JSONObject().put("name", name.ifBlank { "Computer" }.take(40)).put("addresses", JSONArray(addresses)))
        prefs(context).edit().putString("targets", all.toString()).apply()
    }

    /** A computer removed from the account is forgotten here too. */
    fun retain(context: Context, members: Set<String>) {
        val all = runCatching { JSONObject(prefs(context).getString("targets", "{}")!!) }.getOrDefault(JSONObject())
        val gone = all.keys().asSequence().filter { it !in members }.toList()
        if (gone.isEmpty()) return
        gone.forEach(all::remove)
        prefs(context).edit().putString("targets", all.toString()).apply()
    }

    fun targets(context: Context): List<Target> = runCatching {
        val all = JSONObject(prefs(context).getString("targets", "{}")!!)
        all.keys().asSequence().map { id ->
            val item = all.getJSONObject(id)
            val list = item.getJSONArray("addresses")
            Target(id, item.getString("name"), (0 until list.length()).map(list::getString).filter(mac::matches))
        }.filter { it.addresses.isNotEmpty() }.sortedBy { it.name.lowercase() }.toList()
    }.getOrDefault(emptyList())

    /** The standard magic packet: six 0xFF bytes, then the address sixteen times. */
    fun packet(address: String): ByteArray {
        val bytes = address.split(':').map { it.toInt(16).toByte() }
        return ByteArray(6) { 0xFF.toByte() } + ByteArray(16 * 6) { bytes[it % 6] }
    }

    /** Broadcasts to every address, on the usual ports. Off the main thread; true when it went out. */
    fun send(target: Target): Boolean = runCatching {
        DatagramSocket().use { socket ->
            socket.broadcast = true
            val everyone = InetAddress.getByName("255.255.255.255")
            for (address in target.addresses) for (port in intArrayOf(9, 7)) {
                val bytes = packet(address)
                socket.send(DatagramPacket(bytes, bytes.size, everyone, port))
            }
        }
        true
    }.getOrDefault(false)
}
