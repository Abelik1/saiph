package sefirah.network.orion

import android.app.AutomaticZenRule
import android.app.NotificationManager
import android.content.ComponentName
import android.content.Context
import android.net.Uri
import android.os.Build
import android.service.notification.Condition
import kotlinx.serialization.json.*
import org.json.JSONObject
import java.time.Instant
import java.time.ZoneId

/** Orion's own DND rule; never disables a rule owned by Samsung or another app. */
class OrionContinuity(private val context: Context) {
    private val prefs = context.getSharedPreferences("orion_continuity", Context.MODE_PRIVATE)
    private val manager = context.getSystemService(NotificationManager::class.java)
    fun event(frame: JsonObject): Boolean {
        if (frame["type"]?.jsonPrimitive?.content != "focus.plan") return false
        val payload = frame.getValue("payload").jsonObject
        validatePlan(payload)
        prefs.edit().putString("focus_plan", payload.toString()).commit()
        tick()
        return true
    }
    fun restore() {
        val state = JSONObject(Api.request(context, "/v1/link/continuity"))
        prefs.edit().putString("wake_targets",state.optJSONArray("wake_targets")?.toString() ?: "[]").apply()
        val focus = state.optJSONObject("focus") ?: return
        val payload = Json.parseToJsonElement(focus.getJSONObject("payload").toString()).jsonObject
        validatePlan(payload)
        prefs.edit().putString("focus_plan", payload.toString()).commit()
        tick()
    }
    fun tick(now: Instant = Instant.now()): Boolean {
        val saved = prefs.getString("focus_plan", null) ?: return false
        val plan = Json.parseToJsonElement(saved).jsonObject
        val active = active(plan, now) && context.getSharedPreferences("orion", Context.MODE_PRIVATE).getBoolean("focus_enabled", true)
        if (!manager.isNotificationPolicyAccessGranted) return false
        // Direct app toggles are converted into implicit rules by Android 15;
        // explicitly owning a rule avoids altering the user's global DND setting.
        if (Build.VERSION.SDK_INT < 29) return false
        val conditionId = Uri.parse("condition://${context.packageName}/orion/sleep")
        var id = prefs.getString("focus_rule", null)
        if (id == null || manager.getAutomaticZenRule(id) == null) {
            val activity = ComponentName(context.packageName, "com.orionmini.mobile.OrionActivity")
            @Suppress("DEPRECATION")
            val rule = AutomaticZenRule("Saiph sleep plan", null, activity, conditionId, null, NotificationManager.INTERRUPTION_FILTER_PRIORITY, true)
            id = manager.addAutomaticZenRule(rule)
            prefs.edit().putString("focus_rule", id).commit()
        }
        manager.setAutomaticZenRuleState(id, Condition(conditionId, "Saiph sleep plan", if (active) Condition.STATE_TRUE else Condition.STATE_FALSE))
        return active
    }
    companion object {
        fun validatePlan(plan: JsonObject) {
            require(plan.keys == setOf("enabled", "timezone", "start_hour", "start_minute", "end_hour", "end_minute"))
            plan.getValue("enabled").jsonPrimitive.boolean
            ZoneId.of(plan.getValue("timezone").jsonPrimitive.content)
            for (key in listOf("start_hour", "end_hour")) require(plan.getValue(key).jsonPrimitive.int in 0..23)
            for (key in listOf("start_minute", "end_minute")) require(plan.getValue(key).jsonPrimitive.int in 0..59)
        }
        fun active(plan: JsonObject, now: Instant): Boolean {
            validatePlan(plan)
            if (!plan.getValue("enabled").jsonPrimitive.boolean) return false
            val local = now.atZone(ZoneId.of(plan.getValue("timezone").jsonPrimitive.content))
            val minute = local.hour * 60 + local.minute
            val start = plan.getValue("start_hour").jsonPrimitive.int * 60 + plan.getValue("start_minute").jsonPrimitive.int
            val end = plan.getValue("end_hour").jsonPrimitive.int * 60 + plan.getValue("end_minute").jsonPrimitive.int
            return if (start == end) false else if (start < end) minute >= start && minute < end else minute >= start || minute < end
        }
    }
}
