// SPDX-License-Identifier: GPL-3.0-only
package sefirah.network.orion

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.serialization.json.*

data class RemoteControl(val id: String, val label: String, val kind: String, val max: Int)
data class RemoteApp(val id: String, val name: String, val available: Boolean, val controls: List<RemoteControl>)
data class RemoteResult(val source: String, val app: String, val control: String, val ok: Boolean, val message: String)

/** Catalogs and results computers send to this phone's remote screen. Display data only. */
object OrionRemote {
    val catalogs = MutableStateFlow<Map<String, List<RemoteApp>>>(emptyMap())
    val result = MutableStateFlow<RemoteResult?>(null)
    private val ident = Regex("[a-z_]{1,32}")
    fun receive(event: JsonObject): Boolean {
        val type = event["type"]?.jsonPrimitive?.content ?: return false
        if (type != "remote.catalog" && type != "remote.result") return false
        val source = event.getValue("source").jsonPrimitive.content
        val payload = event.getValue("payload").jsonObject
        if (type == "remote.catalog") catalogs.value = catalogs.value + (source to parse(payload))
        else result.value = RemoteResult(source, text(payload, "app", 32), text(payload, "control", 32),
            payload.getValue("ok").jsonPrimitive.boolean, text(payload, "message", 200))
        return true
    }
    private fun text(value: JsonObject, key: String, limit: Int): String {
        val primitive = value.getValue(key).jsonPrimitive
        require(primitive.isString && primitive.content.length <= limit)
        return primitive.content
    }
    fun parse(payload: JsonObject): List<RemoteApp> {
        require(payload.keys == setOf("apps"))
        val apps = payload.getValue("apps").jsonArray
        require(apps.size <= 16)
        return apps.map { element ->
            val app = element.jsonObject
            require(app.keys == setOf("id", "name", "available", "controls"))
            val controls = app.getValue("controls").jsonArray
            require(controls.size <= 16)
            RemoteApp(text(app, "id", 32).also { require(ident.matches(it)) }, text(app, "name", 60), app.getValue("available").jsonPrimitive.boolean,
                controls.map { item ->
                    val control = item.jsonObject
                    require(control.keys - setOf("max") == setOf("id", "label", "kind"))
                    val kind = text(control, "kind", 6)
                    require(kind == "button" || kind == "text")
                    RemoteControl(text(control, "id", 32).also { require(ident.matches(it)) }, text(control, "label", 60), kind,
                        control["max"]?.jsonPrimitive?.int?.coerceIn(1, 500) ?: 500)
                })
        }
    }
    fun command(app: String, control: String, text: String? = null) = buildJsonObject {
        put("app", app); put("control", control); text?.let { put("text", it) }
    }
}
