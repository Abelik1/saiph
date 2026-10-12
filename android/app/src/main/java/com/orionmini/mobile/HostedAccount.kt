// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.content.Context
import android.net.Uri
import android.util.AtomicFile
import com.google.crypto.tink.integration.android.AndroidKeystore
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import net.openid.appauth.*
import okhttp3.*
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.MediaType.Companion.toMediaType
import org.json.JSONObject
import java.io.File
import kotlin.coroutines.resume
import kotlin.coroutines.suspendCoroutine

/** Access tokens are memory-only; the optional rotating refresh token is Keystore protected. */
class HostedAccount private constructor(private val context: Context) {
    companion object {
        @Volatile private var instance: HostedAccount? = null
        fun get(context: Context): HostedAccount = instance ?: synchronized(this) {
            instance ?: HostedAccount(context.applicationContext).also { instance = it }
        }
        const val REDIRECT = "com.orionmini.mobile.hosted:/oauth2redirect"
    }
    private val prefs get() = context.getSharedPreferences("orion_hosted", 0)
    private val tokenLock = Mutex()
    private val file get() = AtomicFile(File(context.noBackupFilesDir, "hosted-refresh.enc"))
    private val alias = "orion_hosted_account_v1"
    private var access: String? = null
    private var expires = 0L
    @Volatile private var generation = 0
    @Volatile var error = ""
        private set
    private fun contextBinding() = listOf("Orion/hosted-account/v1", prefs.getString("issuer", ""), prefs.getString("audience", ""), prefs.getString("client_id", "")).joinToString("\u0000").toByteArray()
    fun configuration(): AuthorizationServiceConfiguration {
        val issuer = prefs.getString("issuer", "")!!
        return AuthorizationServiceConfiguration(Uri.parse(issuer + "authorize"), Uri.parse(issuer + "oauth/token"))
    }
    @Synchronized fun signedIn() = !prefs.getBoolean("signed_out", false) && ((access != null && expires > System.currentTimeMillis() + 60_000) || (prefs.getBoolean("refresh_tokens", false) && file.baseFile.exists()))
    @Synchronized fun request(): AuthorizationRequest {
        check(prefs.getBoolean("enabled", false))
        val builder = AuthorizationRequest.Builder(configuration(), prefs.getString("client_id", "")!!, ResponseTypeValues.CODE, Uri.parse(REDIRECT))
            .setAdditionalParameters(mapOf("audience" to prefs.getString("audience", "")!!))
        if (prefs.getBoolean("refresh_tokens", false)) builder.setScope("offline_access")
        val request = builder.build()
        check(request.codeVerifier != null && request.codeVerifierChallengeMethod == "S256")
        generation++ // A newer browser attempt supersedes any in-flight token exchange.
        check(prefs.edit().putString("pending_state", request.state).putLong("pending_until", System.currentTimeMillis() + 300_000).commit())
        return request
    }
    suspend fun complete(response: AuthorizationResponse) = tokenLock.withLock {
        val epoch = synchronized(this) {
            val expected = prefs.getString("pending_state", null)
            val until = prefs.getLong("pending_until", 0)
            check(prefs.getBoolean("enabled", false) && expected != null && expected == response.state && until > System.currentTimeMillis())
            check(response.request.redirectUri.toString() == REDIRECT && response.request.clientId == prefs.getString("client_id", "") &&
                response.request.configuration.tokenEndpoint == configuration().tokenEndpoint)
            // A stale callback must not consume the state of a newer browser attempt.
            check(prefs.edit().remove("pending_state").remove("pending_until").commit())
            generation
        }
        val grant = exchange(response.createTokenExchangeRequest(), epoch)
        accept(grant, epoch, requireRefresh = false)
    }
    private suspend fun exchange(request: TokenRequest, epoch: Int): TokenResponse = suspendCoroutine { continuation ->
        val service = AuthorizationService(context)
        service.performTokenRequest(request) { response, exception ->
            service.dispose()
            if (response == null || exception != null) {
                synchronized(this) {
                    if (generation == epoch) {
                        error = if (exception?.error == "invalid_grant") "Sign in again." else "Sign-in service is unavailable. Try again."
                        if (exception?.error == "invalid_grant") signOut()
                    }
                }
                continuation.resumeWith(Result.failure(IllegalStateException(error)))
            } else continuation.resume(response)
        }
    }
    @Synchronized private fun accept(grant: TokenResponse, epoch: Int, requireRefresh: Boolean) {
        check(epoch == generation && prefs.getBoolean("enabled", false))
        val value = grant.accessToken ?: error("Sign-in did not return an access token.")
        check(value.length in 1..16384 && value.all { it.code in 33..126 } && grant.tokenType.equals("Bearer", true))
        val expiry = grant.accessTokenExpirationTime ?: error("Sign-in did not return an expiry.")
        check(expiry in System.currentTimeMillis() + 1000..System.currentTimeMillis() + 86_400_000)
        if (prefs.getBoolean("refresh_tokens", false)) {
            val refresh = grant.refreshToken
            check(!requireRefresh || refresh != null)
            if (refresh != null) {
                check(refresh.length in 1..4096 && refresh.all { it.code in 33..126 })
                if (!AndroidKeystore.hasKey(alias)) {
                    check(!file.baseFile.exists())
                    AndroidKeystore.generateNewAes256GcmKey(alias)
                }
                val wrapped = AndroidKeystore.getAead(alias).encrypt(refresh.toByteArray(), contextBinding())
                val output = file.startWrite()
                try { output.write(wrapped); file.finishWrite(output) } catch (failure: Exception) { file.failWrite(output); throw failure }
            } else { file.delete() }
        }
        check(prefs.edit().putBoolean("signed_out", false).commit())
        access = value; expires = expiry; error = ""
    }
    suspend fun token(): String = tokenLock.withLock {
        synchronized(this) { access?.takeIf { expires > System.currentTimeMillis() + 60_000 } }?.let { return@withLock it }
        check(!prefs.getBoolean("signed_out", false) && prefs.getBoolean("enabled", false) && prefs.getBoolean("refresh_tokens", false) && file.baseFile.exists()) { "Sign in again." }
        val raw = file.readFully()
        check(raw.size in 1..16384 && AndroidKeystore.hasKey(alias))
        val refresh = String(AndroidKeystore.getAead(alias).decrypt(raw, contextBinding()))
        val epoch = generation
        val request = TokenRequest.Builder(configuration(), prefs.getString("client_id", "")!!).setGrantType("refresh_token").setRefreshToken(refresh).build()
        accept(exchange(request, epoch), epoch, requireRefresh = true)
        synchronized(this) { access!! }
    }
    @Synchronized fun cancel() { generation++; prefs.edit().remove("pending_state").remove("pending_until").commit() }
    @Synchronized fun signOut() {
        cancel(); access = null; expires = 0
        check(prefs.edit().putBoolean("signed_out", true).commit())
        val refresh = runCatching { if (file.baseFile.exists() && AndroidKeystore.hasKey(alias)) String(AndroidKeystore.getAead(alias).decrypt(file.readFully(), contextBinding())) else null }.getOrNull()
        file.delete()
        HostedRuntime.get(context).invalidate()
        if (refresh != null) {
            val client = OkHttpClient.Builder().followRedirects(false).followSslRedirects(false).cookieJar(CookieJar.NO_COOKIES)
                .proxy(java.net.Proxy.NO_PROXY).callTimeout(15, java.util.concurrent.TimeUnit.SECONDS).build()
            val body = JSONObject().put("client_id", prefs.getString("client_id", "")).put("token", refresh).toString().toRequestBody("application/json".toMediaType())
            client.newCall(Request.Builder().url(prefs.getString("issuer", "") + "oauth/revoke").post(body).build()).enqueue(object : Callback {
                override fun onFailure(call: Call, failure: java.io.IOException) { client.dispatcher.executorService.shutdown() }
                override fun onResponse(call: Call, response: Response) { response.close(); client.dispatcher.executorService.shutdown() }
            })
        }
    }
}
