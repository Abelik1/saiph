// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.content.Context

internal object AppPolicy {
    const val PRIVACY_URL = "https://usesaiph.com/account-privacy.html#app"
    const val TERMS_URL = "https://usesaiph.com/terms.html"
    private const val VERSION = "2026-10-16"
    fun acknowledged(context: Context) = context.getSharedPreferences("orion_policy", 0).getString("acknowledged", null) == VERSION
    fun acknowledge(context: Context) {
        check(context.getSharedPreferences("orion_policy", 0).edit().putString("acknowledged", VERSION).commit())
    }
}
