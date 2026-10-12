package com.orionmini.mobile

import android.content.Context
import android.content.ContextWrapper
import android.content.SharedPreferences
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import sefirah.network.orion.Api
import sefirah.network.orion.MeshOrigin
import java.io.File
import java.util.UUID

/** Safe on the owner's paired phone: fixtures use separate preferences/cache files. */
@RunWith(AndroidJUnit4::class)
class ConnectionPreflightTest {
    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext

    @Test fun priorMeshMigrationPreservesIdentityAndCompletedSetup() {
        val fixture = context.getSharedPreferences("orion_migration_test_" + UUID.randomUUID(), Context.MODE_PRIVATE)
        val isolated = object : ContextWrapper(context) {
            override fun getSharedPreferences(name: String, mode: Int): SharedPreferences =
                if (name == "orion") fixture else super.getSharedPreferences(name, mode)
        }
        try {
            fixture.edit().putString("base_url", "http://100.64.0.2:8765")
                .putBoolean("mesh_migrated", true).putString("device_id", "existing-test-identity")
                .putBoolean("setup_done", true).commit()
            assertEquals("http://100.64.0.2:8765", Api.base(isolated))
            assertEquals("http://100.64.0.2:8765", fixture.getString("base_url", null))
            assertEquals("existing-test-identity", fixture.getString("device_id", null))
            assertTrue(fixture.getBoolean("setup_done", false))
            // Applying the migration again must retain the same identity and origin.
            Api.migrateMesh(isolated)
            assertEquals("existing-test-identity", fixture.getString("device_id", null))
        } finally { fixture.edit().clear().commit() }
    }

    @Test fun realPairingSignsMeshPresenceWithoutChangingIdentity() {
        val prefs = context.getSharedPreferences("orion", Context.MODE_PRIVATE)
        val identity = prefs.getString("device_id", null)
        assertNotNull("Provision the phone before running live acceptance", identity)
        val completed = prefs.getBoolean("setup_done", false)
        val devices = JSONObject(Api.request(context, "/v1/link/devices")).getJSONArray("devices")
        assertTrue((0 until devices.length()).any { devices.getJSONObject(it).getString("id") == identity })
        assertEquals(identity, prefs.getString("device_id", null))
        assertEquals(completed, prefs.getBoolean("setup_done", false))
    }

    @Test fun independentHubSurvivesUpgradeWithOrWithoutMigrationMarker() {
        val fixture = context.getSharedPreferences("orion_friend_test_"+UUID.randomUUID(), Context.MODE_PRIVATE)
        val isolated = object : ContextWrapper(context) {
            override fun getSharedPreferences(name:String,mode:Int):SharedPreferences =
                if(name=="orion")fixture else super.getSharedPreferences(name,mode)
        }
        try {
            for(migrated in listOf(false,true)) {
                fixture.edit().clear().putString("base_url","http://100.100.10.2:12345")
                    .putBoolean("mesh_migrated",migrated).putString("device_id","existing-friend-identity")
                    .putBoolean("setup_done",true).commit()
                repeat(2) { assertEquals("http://100.100.10.2:12345",Api.base(isolated)) }
                assertEquals("existing-friend-identity",fixture.getString("device_id",null))
                assertTrue(fixture.getBoolean("setup_done",false))
                assertTrue(runCatching { Api.pair(isolated,MeshOrigin.DEFAULT,"12345678","test") }.isFailure)
                assertEquals("http://100.100.10.2:12345",fixture.getString("base_url",null))
            }
            fixture.edit().putString("base_url","http://attacker.example:8765").commit()
            Api.migrateMesh(isolated)
            assertTrue(runCatching { Api.base(isolated) }.isFailure)
            assertEquals("existing-friend-identity",fixture.getString("device_id",null))
        } finally { fixture.edit().clear().commit() }
    }

    @Test fun signedUpdateDownloadPassesIntegrityOnRealMesh() {
        val release = JSONObject(Api.request(context, "/v1/app/android")).getJSONObject("release")
        val target = File(context.cacheDir, "preflight-" + UUID.randomUUID() + ".apk")
        try {
            Api.download(context, "/v1/app/android/apk", target)
            Updater.verify(target, release)
            assertEquals(release.getLong("size"), target.length())
        } finally { target.delete() }
    }
}
