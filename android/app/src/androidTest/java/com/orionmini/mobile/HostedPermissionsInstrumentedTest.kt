// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.Manifest
import android.accessibilityservice.AccessibilityServiceInfo
import android.content.pm.PackageManager
import android.view.accessibility.AccessibilityNodeInfo
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

/** Actual Android permission dialogs, using only a fresh disposable emulator. No account or device. */
@RunWith(AndroidJUnit4::class)
class HostedPermissionsInstrumentedTest {
    @Test fun deniedPhotoPermissionHasAWorkingSettingsFallback() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val prefs = context.getSharedPreferences("orion_hosted", 0)
        assertFalse("Fresh isolated profile required", prefs.contains("device_id"))
        assertFalse(HostedAccount.get(context).signedIn())
        assertNotEquals(PackageManager.PERMISSION_GRANTED, context.checkSelfPermission(Manifest.permission.READ_MEDIA_IMAGES))
        prefs.edit().clear().commit()
        AppPolicy.acknowledge(context)
        val automation = instrumentation.uiAutomation
        automation.serviceInfo = automation.serviceInfo.apply { flags = flags or AccessibilityServiceInfo.FLAG_REPORT_VIEW_IDS }
        fun waitFor(packageName: String, find: (AccessibilityNodeInfo) -> AccessibilityNodeInfo?): AccessibilityNodeInfo {
            var lastPackage = ""
            repeat(80) {
                val root = automation.rootInActiveWindow
                lastPackage = root?.packageName?.toString() ?: "none"
                if (root != null) find(root)?.takeIf { it.packageName?.toString()?.endsWith(packageName) == true }?.let { return it }
                Thread.sleep(100)
            }
            error("Expected Android UI did not appear: $packageName (last window: $lastPackage)")
        }
        fun denyButton(node: AccessibilityNodeInfo): AccessibilityNodeInfo? {
            if (node.viewIdResourceName?.endsWith(":id/permission_deny_button") == true ||
                node.text?.toString()?.replace('’', '\'')?.equals("Don't allow", ignoreCase = true) == true) return node
            for (index in 0 until node.childCount) node.getChild(index)?.let { denyButton(it)?.let { return it } }
            return null
        }
        fun click(node: AccessibilityNodeInfo) { assertTrue(node.performAction(AccessibilityNodeInfo.ACTION_CLICK)); instrumentation.waitForIdleSync() }
        ActivityScenario.launch(HostedActivity::class.java).use { scenario ->
            fun request() = scenario.onActivity { activity ->
                HostedActivity::class.java.getDeclaredMethod("requestSharingPermissions", String::class.java)
                    .apply { isAccessible = true }.invoke(activity, "photos")
            }
            repeat(2) {
                request()
                val deny = waitFor(".permissioncontroller", ::denyButton)
                click(deny)
                click(waitFor(context.packageName) { it.findAccessibilityNodeInfosByText("Not now").firstOrNull() })
            }
            request() // Android no longer shows a dialog. The app must open Settings instead.
            waitFor("com.android.settings") { it }
            assertNotEquals(PackageManager.PERMISSION_GRANTED, context.checkSelfPermission(Manifest.permission.READ_MEDIA_IMAGES))
            assertFalse(HostedRuntime.get(context).photosShared()) // Asking alone cannot opt in.
        }
        prefs.edit().clear().commit()
    }
}
