// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.Manifest
import android.content.pm.PackageManager
import androidx.lifecycle.Lifecycle
import androidx.test.core.app.ActivityScenario
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

class PhoneCameraInstrumentedTest {
    @Test fun nativePinnedTlsCameraXFramesAndLeavingScreenStopsCapture() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        // A fresh one-use, synthetic loopback offer is provisioned only by the
        // disposable-emulator harness after assembly. Never use a live account.
        val fixture = File(context.cacheDir, "camera-session-test.json")
        assumeTrue("Isolated local TLS camera fixture required", fixture.isFile)
        val code = Json.parseToJsonElement(fixture.readText()).jsonObject.getValue("code").jsonPrimitive.content
        fixture.delete()
        val offer = CameraOffer.parse(code)
        assertFalse(context.getSharedPreferences("orion_hosted", 0).contains("device_id"))
        assertFalse(context.getSharedPreferences("orion", 0).contains("device_id"))
        assertFalse(AppLock.enabled(context))
        AppPolicy.acknowledge(context)
        val rejected = CountDownLatch(1)
        val wrong = CameraOffer(offer.session, offer.addresses, offer.port, "0".repeat(64), offer.secret, offer.expires)
        val bad = CameraSender(wrong, connected = { fail("Wrong certificate was trusted") }, ended = { rejected.countDown() })
        bad.connect()
        assertTrue("Pinned TLS must reject an unknown certificate", rejected.await(10, TimeUnit.SECONDS))
        bad.close()
        instrumentation.uiAutomation.grantRuntimePermission(context.packageName, Manifest.permission.CAMERA)
        assertEquals(PackageManager.PERMISSION_GRANTED, context.checkSelfPermission(Manifest.permission.CAMERA))
        ActivityScenario.launch(PhoneCameraActivity::class.java).use { scenario ->
            lateinit var capturedActivity: PhoneCameraActivity
            scenario.moveToState(Lifecycle.State.STARTED)
            scenario.onActivity { activity ->
                capturedActivity = activity
                PhoneCameraActivity::class.java.getDeclaredField("offer").apply { isAccessible = true }.set(activity, offer)
                // The synthetic test invokes the capture controller directly;
                // native owner verification is retained and is not claimed here.
                PhoneCameraActivity::class.java.getDeclaredMethod("approvedStart").apply { isAccessible = true }.invoke(activity)
                assertNull("A permission/verification result must wait for the activity to resume",
                    PhoneCameraActivity::class.java.getDeclaredField("sender").apply { isAccessible = true }.get(activity))
            }
            scenario.moveToState(Lifecycle.State.RESUMED)
            var sent = 0L
            repeat(150) {
                if (sent < 3) {
                    Thread.sleep(100)
                    scenario.onActivity { activity ->
                        val sender = PhoneCameraActivity::class.java.getDeclaredField("sender").apply { isAccessible = true }.get(activity) as? CameraSender
                        sent = sender?.framesSent ?: 0
                    }
                }
            }
            assertTrue("CameraX must send native camera frames over pinned TLS", sent >= 3)
            Thread.sleep(15000) // Allow the real Qt shell to observe and capture the synthetic preview.
            scenario.moveToState(Lifecycle.State.CREATED)
            instrumentation.runOnMainSync {
                assertNull(PhoneCameraActivity::class.java.getDeclaredField("sender").apply { isAccessible = true }.get(capturedActivity))
                assertNull(PhoneCameraActivity::class.java.getDeclaredField("provider").apply { isAccessible = true }.get(capturedActivity))
            }
        }
        // The outer disposable-emulator harness clears this profile afterwards.
        // Revoking this app's permission here would kill its instrumentation.
    }
}
