package com.orionmini.mobile

import android.widget.Button
import android.widget.TextView
import android.view.View
import android.view.ViewGroup
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.castle.sefirah.BuildConfig
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.security.MessageDigest

@RunWith(AndroidJUnit4::class)
class UpdateIntegrationTest {
    @Test fun settingsExposesManualUpdateWithoutAConnectionControl() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val prefs = context.getSharedPreferences("orion", 0)
        assumeTrue(prefs.contains("device_id"))
        val previous = prefs.getBoolean("setup_done", false)
        prefs.edit().putBoolean("setup_done", true).commit()
        try {
            ActivityScenario.launch(OrionActivity::class.java).use { scenario ->
                scenario.onActivity { activity ->
                    fun views(view: View): List<View> = listOf(view) + if (view is ViewGroup)
                        (0 until view.childCount).flatMap { views(view.getChildAt(it)) } else emptyList()
                    val root = activity.window.decorView
                    views(root).filterIsInstance<Button>().single { it.text == "Settings" }.performClick()
                    val buttons = views(root).filterIsInstance<Button>().map { it.text.toString() }
                    assertTrue(buttons.contains("Check for updates"))
                    assertFalse(buttons.any { it in setOf("Connect", "Refresh", "Sync") })
                    assertTrue(views(root).filterIsInstance<TextView>().any { it.text.contains(BuildConfig.VERSION_NAME) })
                }
            }
        } finally { prefs.edit().putBoolean("setup_done", previous).commit() }
    }

    @Test fun corruptDownloadedUpdateIsDeletedAndInstalledVersionIsNotAnUpdate() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val file = File(context.cacheDir, "update-integrity-test.apk")
        val content = "test APK bytes".toByteArray()
        val digest = MessageDigest.getInstance("SHA-256").digest(content).joinToString("") { "%02x".format(it) }
        val release = JSONObject().put("sha256", digest).put("version_code", BuildConfig.VERSION_CODE)
        try {
            file.writeBytes(content); Updater.verify(file, release)
            assertFalse(Updater.isNewer(release))
            release.put("version_code", BuildConfig.VERSION_CODE + 1)
            assertTrue(Updater.isNewer(release))
            file.appendText("corruption")
            assertThrows(IllegalStateException::class.java) { Updater.verify(file, release) }
            assertFalse("Unverified APK must not remain installable", file.exists())
        } finally { file.delete() }
    }
}
