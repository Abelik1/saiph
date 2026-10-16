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
}
