// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import java.net.URI

/** Provider routing changes the browser destination, never the token issuer or account identity. */
internal object HostedSignIn {
    const val PLANS_URL = "https://usesaiph.com/hosted.html"
    fun scope(refresh: Boolean) = "openid email" + if (refresh) " offline_access" else ""
    /** Which sign-in page opens: Google's account chooser, Auth0's email-and-password form, or
     * (for accounts made before the choice existed) Auth0's own page with every option. */
    enum class Method { GOOGLE, EMAIL, ANY }
    /** Auth0's email-and-password connection: sign-up, verification and password reset happen there. */
    const val EMAIL_CONNECTION = "Username-Password-Authentication"
    /** Extra query parameters for Auth0. AppAuth builds its own parameters (prompt, scope, state,
     * redirect_uri and so on) and refuses them here, so [prompt] travels through the builder. */
    fun parameters(issuer: String, audience: String, method: Method = Method.GOOGLE): Map<String, String> = buildMap {
        put("audience", audience)
        if (!auth0(issuer)) return@buildMap
        when (method) {
            Method.GOOGLE -> put("connection", "google-oauth2")
            Method.EMAIL -> put("connection", EMAIL_CONNECTION)
            Method.ANY -> Unit
        }
    }
    /** The OpenID prompt for AuthorizationRequest.Builder.setPrompt, or null for none. */
    fun prompt(issuer: String, method: Method = Method.GOOGLE): String? = if (!auth0(issuer)) null else when (method) {
        // Always ask which Google account: browser sessions outlive signing out of Saiph.
        Method.GOOGLE -> "select_account"
        // Always show the email form, even after a Google sign-in in the same browser.
        Method.EMAIL -> "login"
        Method.ANY -> null
    }
    private fun auth0(issuer: String) = URI(issuer).host?.lowercase()?.endsWith(".auth0.com") == true
    /** Never display provider bodies, URLs, tokens or arbitrary exception text. */
    fun issue(failure: Throwable): HostedSignInIssue =
        (failure as? HostedSignInException)?.issue ?: HostedSignInIssue.UNAVAILABLE
}

internal enum class HostedSignInIssue(val code: String, val message: String) {
    CALLBACK("callback_rejected", "This sign-in attempt expired or was replaced. Start sign-in again. Your phone approval is kept."),
    GRANT("grant_rejected", "The sign-in service rejected this attempt. Start sign-in again. Your phone approval is kept."),
    CONFIGURATION("client_configuration", "The service has not enabled this Android sign-in request. Your phone approval is kept."),
    PERSISTENT_SESSION("persistent_session_required", "The service did not provide a persistent Android session. Its Android sign-in settings need attention. Your phone approval is kept."),
    RESPONSE("invalid_token_response", "The sign-in service returned a response Saiph could not use. Try signing in again. Your phone approval is kept."),
    STORAGE("protected_storage", "Saiph could not securely save your sign-in on this phone. Your phone approval is kept. Try again after unlocking your phone."),
    UNAVAILABLE("service_unavailable", "Saiph could not reach the sign-in service. Check your connection and try again. Your phone approval is kept.")
}

internal class HostedSignInException(val issue: HostedSignInIssue) : IllegalStateException(issue.message)
