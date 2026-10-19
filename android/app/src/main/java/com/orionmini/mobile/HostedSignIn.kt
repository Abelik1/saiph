// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import java.net.URI

/** Provider routing changes the browser destination, never the token issuer or account identity. */
internal object HostedSignIn {
    const val PLANS_URL = "https://usesaiph.com/hosted.html"
    fun parameters(issuer: String, audience: String, google: Boolean = true): Map<String, String> = buildMap {
        put("audience", audience)
        if (google && URI(issuer).host?.lowercase()?.endsWith(".auth0.com") == true)
            put("connection", "google-oauth2")
    }
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
