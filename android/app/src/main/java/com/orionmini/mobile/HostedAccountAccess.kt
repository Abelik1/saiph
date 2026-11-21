// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.content.Context
import kotlinx.serialization.json.*
import okhttp3.CookieJar
import okhttp3.OkHttpClient
import okhttp3.Request
import java.net.Proxy
import java.util.concurrent.TimeUnit

/** Read-only account access refresh before pairing. Trials start in website Stripe Checkout. */
internal object HostedAccountAccess {
    fun matchesDeployment(defaults: JsonObject, origin: String, issuer: String, audience: String, client: String) =
        (defaults["service_url"] as? JsonPrimitive)?.content?.trimEnd('/') == origin &&
        defaults["issuer"] == JsonPrimitive(issuer) && defaults["audience"] == JsonPrimitive(audience) &&
        defaults["android_client_id"] == JsonPrimitive(client)
    private val client by lazy {
        OkHttpClient.Builder().followRedirects(false).followSslRedirects(false).retryOnConnectionFailure(false)
            .cookieJar(CookieJar.NO_COOKIES).proxy(Proxy.NO_PROXY)
            .callTimeout(20, TimeUnit.SECONDS).build()
    }
    /** Only read access from the build's matching public Cloud deployment. */
    fun available(context: Context): Boolean = runCatching {
        val prefs = context.getSharedPreferences("orion_hosted", 0)
        val raw = context.assets.open("hosted-defaults.json").use { it.readBytes() }
        check(raw.size <= 4096)
        val defaults = Json.parseToJsonElement(raw.toString(Charsets.UTF_8)).jsonObject
        matchesDeployment(defaults, prefs.getString("origin", "")!!, prefs.getString("issuer", "")!!,
            prefs.getString("audience", "")!!, prefs.getString("client_id", "")!!)
    }.getOrDefault(false)

    private fun json(request: Request): Pair<Int, JsonObject> = client.newCall(request).execute().use { response ->
        val body = response.body ?: error("Missing response")
        check(body.contentLength() <= 4096)
        val bytes = body.byteStream().use { input ->
            val output = java.io.ByteArrayOutputStream()
            val buffer = ByteArray(1024)
            while (true) {
                val count = input.read(buffer)
                if (count < 0) break
                check(output.size() + count <= 4096)
                output.write(buffer, 0, count)
            }
            output.toByteArray()
        }
        check(bytes.size <= 4096)
        response.code to Json.parseToJsonElement(bytes.toString(Charsets.UTF_8)).jsonObject
    }
    /** Read Cloud access on a worker; no subscription or trial activation request is sent. */
    fun refresh(context: Context, token: String, gate: () -> Boolean): HostedTrial.Access? {
        if (!available(context) || !gate()) return null
        val prefs = context.getSharedPreferences("orion_hosted", 0)
        val origin = prefs.getString("origin", "")!!
        fun access(): HostedTrial.Access? {
            if (!gate()) return null
            val (status, value) = json(Request.Builder().url("$origin/v1/access").header("Authorization", "Bearer $token").build())
            return if (status == 200 && gate()) HostedTrial.parse(value) else null
        }
        val current = access() ?: return null
        return current
    }
}
