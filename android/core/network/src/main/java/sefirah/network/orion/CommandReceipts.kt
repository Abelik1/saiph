package sefirah.network.orion

import android.content.Context
import org.json.JSONObject

/** At-most-once command execution across reconnects and process restarts. */
class CommandReceipts(context: Context) {
    private val prefs = context.getSharedPreferences("orion_command_receipts", Context.MODE_PRIVATE)
    @Synchronized fun claim(id: String): Boolean {
        val now = System.currentTimeMillis()
        val saved = runCatching { JSONObject(prefs.getString("ids", "{}")!!) }.getOrDefault(JSONObject())
        val keys = saved.keys().asSequence().toList()
        keys.filter { now - saved.optLong(it) > 86400000L }.forEach(saved::remove)
        if (saved.has(id)) return false
        // Never evict an unexpired command and risk repeating an outgoing action.
        check(saved.length() < 2000) { "Command receipt capacity reached" }
        saved.put(id, now)
        check(prefs.edit().putString("ids", saved.toString()).commit()) { "Command receipt unavailable" }
        return true
    }
}
