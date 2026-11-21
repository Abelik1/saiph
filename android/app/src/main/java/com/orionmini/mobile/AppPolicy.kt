// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.content.Context
import java.net.URI

internal object AppPolicy {
    const val PRIVACY_URL = "https://usesaiph.com/account-privacy.html#app"
    const val TERMS_URL = "https://usesaiph.com/terms.html"
    const val SUPPORT_EMAIL = "support@usesaiph.com"

    /**
     * The account deletion page (Google Play User Data policy) on the account site this build
     * was given (`-PorionAccountOrigin`, BuildConfig.ACCOUNT_ORIGIN): `<origin>/account/delete`.
     * It explains what is deleted and takes the request; it shows no plans or prices, so both the
     * Play and direct builds open it. Null when the build has no canonical HTTPS account origin.
     */
    fun deletionUrl(accountOrigin: String): String? = runCatching {
        val uri = URI(accountOrigin)
        check(uri.scheme == "https" && !uri.host.isNullOrBlank() && uri.rawUserInfo == null && uri.port == -1 &&
            uri.rawPath.isNullOrEmpty() && uri.rawQuery == null && uri.rawFragment == null)
        "https://${uri.host.lowercase()}/account/delete"
    }.getOrNull()
    private const val VERSION = "2026-10-16"
    fun acknowledged(context: Context) = context.getSharedPreferences("orion_policy", 0).getString("acknowledged", null) == VERSION
    fun acknowledge(context: Context) {
        check(context.getSharedPreferences("orion_policy", 0).edit().putString("acknowledged", VERSION).commit())
    }
}
