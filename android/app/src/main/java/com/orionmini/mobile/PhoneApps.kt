// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.content.Context
import android.content.Intent

/** Apps with a launcher icon, as (package, label): what the computer may list and open. */
internal object PhoneApps {
    fun list(context: Context): List<Pair<String, String>> {
        val launcher = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        val manager = context.packageManager
        @Suppress("DEPRECATION")
        return manager.queryIntentActivities(launcher, 0).asSequence()
            .map { it.activityInfo.packageName to it.loadLabel(manager).toString() }
            .filter { it.first != context.packageName }
            .distinctBy { it.first }.sortedBy { it.second.lowercase() }.toList()
    }

    /** The app's own launch intent; null for packages without one (never an arbitrary component). */
    fun launchIntent(context: Context, packageName: String): Intent? {
        if (!ScreenOffer.validPackage(packageName) || packageName == context.packageName) return null
        return context.packageManager.getLaunchIntentForPackage(packageName)
            ?.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED)
    }
}
