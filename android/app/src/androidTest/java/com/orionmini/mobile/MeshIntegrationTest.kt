package com.orionmini.mobile

import android.content.Intent
import androidx.core.content.ContextCompat
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith
import sefirah.network.orion.*
import java.io.File

/** Run only against an explicitly provisioned private one-use test QR. Never log it. */
@RunWith(AndroidJUnit4::class)
class MeshIntegrationTest {
    @Test fun keystorePairingSignedRestAndForegroundBatteryReachRealHub() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val qr = File(context.filesDir, "test-qr")
        val prefs = context.getSharedPreferences("orion", 0)
        assumeTrue(qr.exists() || prefs.contains("device_id"))
        if (!prefs.contains("device_id")) {
            val (origin, code) = MeshOrigin.pairing(qr.readText().trim())
            Api.pair(context, origin, code, "Orion Android emulator acceptance")
        }
        qr.delete()
        ContextCompat.startForegroundService(context, Intent(context, OrionLinkService::class.java))
        val device = prefs.getString("device_id", "")
        var online = false; var battery = false
        val until = System.currentTimeMillis() + 60000
        while ((!online || !battery) && System.currentTimeMillis() < until) {
            val devices = JSONObject(Api.request(context, "/v1/link/devices")).getJSONArray("devices")
            online = (0 until devices.length()).any { devices.getJSONObject(it).let { d -> d.getString("id") == device && d.getBoolean("online") } }
            val events = JSONObject(Api.request(context, "/v1/link/events")).getJSONArray("events")
            battery = (0 until events.length()).any { events.getJSONObject(it).let { e ->
                e.getString("source") == device && e.getString("type") == "battery" && e.getJSONObject("payload").getInt("battery_level") in 0..100
            } }
            if (!online || !battery) Thread.sleep(1000)
        }
        assertTrue("Phone presence must reach the real mesh hub", online)
        assertTrue("Phone battery must reach the real mesh hub", battery)
        assertNotNull(JSONObject(Api.request(context, "/v1/inbox")).getJSONArray("items"))
    }
}
