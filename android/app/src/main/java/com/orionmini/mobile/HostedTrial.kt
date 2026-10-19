// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.longOrNull

/**
 * Free trial notice from the service's `GET /v1/access` (docs/PAID_HOSTED.md): days
 * left, or that Cloud is paused until the owner subscribes. Wording only; the
 * service alone decides access. Same rules as the desktop's hosted_access.py.
 */
internal object HostedTrial {
    /** Fetched again at most this often while connected; a refusal fetches at once. */
    const val REFRESH_MILLIS = 6 * 3600_000L
    const val PAUSED = "Paused: no Cloud access"

    data class Access(val entitled: Boolean, val until: Long?, val kinds: List<String>, val trialUntil: Long?)
    data class Notice(val state: String, val daysLeft: Int?, val title: String, val message: String, val action: String)

    private val KINDS = setOf("admin", "beta", "paid", "trial")

    /** The service's answer, or null when it is not exactly the expected shape. */
    fun parse(value: JsonObject): Access? {
        if (value.keys != setOf("entitled", "until", "kinds") && value.keys != setOf("entitled", "until", "kinds", "trial_until")) return null
        val entitled = (value["entitled"] as? JsonPrimitive)?.takeIf { !it.isString }?.booleanOrNull ?: return null
        val kinds = (value["kinds"] as? JsonArray)?.map { (it as? JsonPrimitive)?.takeIf { p -> p.isString }?.content ?: return null } ?: return null
        if (kinds.size > 8 || kinds.toSet().size != kinds.size || kinds.any { it !in KINDS }) return null
        fun time(name: String): Long? {
            val item = value[name] ?: return null
            if (item is JsonNull) return null
            val number = (item as? JsonPrimitive)?.takeIf { !it.isString }?.longOrNull ?: throw IllegalArgumentException()
            if (number <= 0) throw IllegalArgumentException()
            return number
        }
        val until = runCatching { time("until") }.getOrElse { return null }
        val trialUntil = runCatching { time("trial_until") }.getOrElse { return null }
        if (entitled != (until != null) || entitled != kinds.isNotEmpty()) return null
        return Access(entitled, until, kinds, trialUntil)
    }

    /** Null when there is nothing to say (a subscription or invitation is active, or access is unknown). */
    fun notice(access: Access?, nowSeconds: Long): Notice? {
        access ?: return null
        val trialUntil = access.trialUntil
        if (access.entitled) {
            if (access.kinds != listOf("trial") || trialUntil == null || nowSeconds >= trialUntil) return null
            val days = maxOf(1L, (trialUntil - nowSeconds + 86_399) / 86_400).toInt()
            return Notice("trial", days, "Free trial: $days ${if (days == 1) "day" else "days"} left",
                "Subscribe on the Saiph website to keep Saiph Cloud after your trial. Nothing is charged automatically.", "Subscribe")
        }
        if (trialUntil != null) return Notice("trial_ended", 0, "Your free trial has ended",
            "Subscribe on the Saiph website to reconnect. Nothing was deleted: your devices, approvals and data are kept.", "Subscribe")
        return Notice("none", null, "No Saiph Cloud access yet",
            "Start your free trial or subscribe on the Saiph website with this same account.", "Start free trial or subscribe")
    }

    /** Whether the service is refusing this account, so Cloud is paused rather than waiting. */
    fun refused(access: Access?) = access != null && !access.entitled
}
