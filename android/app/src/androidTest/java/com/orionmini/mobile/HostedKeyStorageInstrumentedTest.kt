// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.core.app.ActivityScenario
import android.database.sqlite.SQLiteDatabase
import android.view.View
import android.view.ViewGroup
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import sefirah.network.orion.*
import java.io.File
import java.security.AlgorithmParameters
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.MessageDigest
import java.security.PrivateKey
import java.security.Signature
import java.security.interfaces.ECKey
import java.security.spec.ECGenParameterSpec
import java.security.spec.ECParameterSpec
import java.util.Base64
import java.util.UUID

/** Run only in a fresh emulator/test profile: uses the real Android Keystore and SQLite. */
@RunWith(AndroidJUnit4::class)
class HostedKeyStorageInstrumentedTest {
    @Test fun protectedIdentityCanCreateReloadAndBuildAnEnrollmentRequest() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        assertFalse("Use a fresh unpaired test profile", context.getSharedPreferences("orion", 0).contains("device_id"))
        assertFalse("Use a fresh Cloud test profile", context.getSharedPreferences("orion_hosted", 0).contains("device_id"))
        Security.ensureKey()
        val keystore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        val signing = keystore.getKey("orion_device_p256", null) as PrivateKey
        assertTrue("Android signing key must expose EC parameters", signing is ECKey)
        val actual = (signing as ECKey).params
        val expected = AlgorithmParameters.getInstance("EC").apply { init(ECGenParameterSpec("secp256r1")) }.getParameterSpec(ECParameterSpec::class.java)
        assertEquals("curve", expected.curve, actual.curve)
        assertEquals("generator", expected.generator, actual.generator)
        assertEquals("order", expected.order, actual.order)
        val probe = byteArrayOf(1, 2, 3)
        val proof = Signature.getInstance("SHA256withECDSA").run { initSign(signing); update(probe); sign() }
        assertTrue(Signature.getInstance("SHA256withECDSA").run { initVerify(keystore.getCertificate("orion_device_p256").publicKey); update(probe); verify(proof) })
        val deployment = UUID.randomUUID().toString()
        val device = "dev_" + UUID.randomUUID().toString().replace("-", "")
        val store = HostedRecipientKeys.forDeployment(context, deployment, device)
        val keys = try { store.create() } catch (failure: Exception) {
            val folder = File(context.noBackupFilesDir, "orion-hosted-keys-v1/$deployment/$device")
            fail("Native protected-key creation failed: lock=${File(folder, "store.lock").exists()}, marker=${File(folder, "created.marker").exists()}, encrypted=${File(folder, "recipient.enc").exists()}, master=${keystore.containsAlias("orion_hosted_recipient_v1_${deployment}_$device")}")
            throw failure
        }
        val recipient = HostedEnvelope.exportPublic(keys.recipient)
        val loaded = store.load(recipient)
        assertEquals(recipient, HostedEnvelope.exportPublic(loaded.recipient))
        val rootSigning = KeyPairGenerator.getInstance("EC").run { initialize(ECGenParameterSpec("secp256r1")); generateKeyPair() }
        val rootKeys = HostedRecipientMaterial(HostedEnvelope.generateRecipient(), rootSigning.private, rootSigning.public)
        val root = HostedRoot(deployment, "dev_" + "1".repeat(32), Base64.getEncoder().encodeToString(rootSigning.public.encoded), HostedEnvelope.exportPublic(rootKeys.recipient))
        val session = HostedSession(root, device, loaded, AndroidHostedTrustStore.create(context, deployment, device))
        val code = HostedApprovalCodes.request(session)
        assertTrue(code.startsWith("orion-approve-v1:"))
        val reopened = HostedSession(root, device, store.load(recipient), AndroidHostedTrustStore.openExisting(context, deployment, device))
        assertFalse(reopened.hasRetainedApproval())
        assertEquals(session.enrollment().getValue("device"), reopened.enrollment().getValue("device"))
        val now = System.currentTimeMillis() / 1000
        fun roster(version: Int, previous: String?, members: List<JsonObject>): JsonObject {
            val value = buildJsonObject {
                put("deployment_id", deployment); put("version", version)
                put("previous_hash", previous?.let(::JsonPrimitive) ?: JsonNull)
                put("expires_at", now + 3600)
                put("members", JsonArray(members.sortedBy { it.getValue("id").jsonPrimitive.content }))
            }
            val signature = Signature.getInstance("SHA256withECDSA").run {
                initSign(rootSigning.private)
                update("Orion hosted roster v1\u0000".toByteArray(Charsets.US_ASCII) + HostedEnvelope.canonical(value)); sign()
            }
            return buildJsonObject { put("roster", value); put("signature", Base64.getEncoder().encodeToString(signature)) }
        }
        val genesis = roster(1, null, listOf(root.member()))
        val hash = MessageDigest.getInstance("SHA-256").digest(HostedEnvelope.canonical(genesis.getValue("roster"))).joinToString("") { "%02x".format(it) }
        val approved = roster(2, hash, listOf(root.member(), session.enrollment().getValue("device").jsonObject))
        val chain = JsonArray(listOf(genesis, approved))
        val computer = HostedSession(root, root.deviceId, rootKeys, AndroidHostedTrustStore.create(context, deployment, root.deviceId))
        computer.acceptChain(chain); reopened.acceptChain(chain)
        val event = computer.encrypt(device, buildJsonObject { put("type", "test.synthetic"); put("text", "emulator-only") })
        assertEquals("emulator-only", reopened.authenticate(event).getValue("text").jsonPrimitive.content)
        assertFalse(reopened.receiveIntoEncryptedInbox(event).duplicate)
        assertTrue(reopened.receiveIntoEncryptedInbox(event).duplicate)
        val restored = HostedSession(root, device, store.load(recipient), AndroidHostedTrustStore.openExisting(context, deployment, device))
        assertTrue(restored.hasRetainedApproval())
        restored.acceptChain(chain)
        assertEquals(listOf(event), restored.pendingIncoming())
        restored.completeIncoming(event.getValue("header").jsonObject.getValue("id").jsonPrimitive.content)
        assertTrue(restored.pendingIncoming().isEmpty())
        val reply = restored.encrypt(root.deviceId, buildJsonObject { put("type", "test.synthetic"); put("text", "phone reply") })
        assertEquals("phone reply", computer.authenticate(reply).getValue("text").jsonPrimitive.content)
    }

    @Test fun restartingAnIncompleteStoreRetainsKeysAndTheAccount() = runBlocking {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val prefs = context.getSharedPreferences("orion_hosted", 0)
        assertFalse("Fresh unpaired test profile required", prefs.contains("device_id"))
        assertFalse(context.getSharedPreferences("orion", 0).contains("device_id"))
        val runtime = HostedRuntime.get(context)
        runtime.configure("https://synthetic.invalid", "https://synthetic.auth0.com/", "synthetic-api", "synthetic-native", false)
        runtime.setEnabled(true)
        val account = HostedAccount.get(context)
        // Memory-only synthetic account; this test never exchanges or submits a token.
        HostedAccount::class.java.getDeclaredField("access").apply { isAccessible = true }.set(account, "synthetic-test-only")
        HostedAccount::class.java.getDeclaredField("expires").apply { isAccessible = true }.setLong(account, System.currentTimeMillis() + 3600_000)
        prefs.edit().putBoolean("signed_out", false).commit()
        val deployment = UUID.randomUUID().toString()
        val device = "dev_" + UUID.randomUUID().toString().replace("-", "")
        Security.ensureKey()
        val keys = HostedRecipientKeys.forDeployment(context, deployment, device)
        val recipient = HostedEnvelope.exportPublic(keys.create().recipient)
        val folder = File(context.noBackupFilesDir, "orion-hosted-trust-v1/$deployment/$device").apply { mkdirs() }
        File(folder, "created.marker").writeText("ORION_HOSTED_TRUST_V1\n")
        val database = File(folder, "trust.sqlite3")
        SQLiteDatabase.openOrCreateDatabase(database, null).use { it.version = 1 }
        val root = buildJsonObject { put("deployment", deployment); put("id", "dev_" + "1".repeat(32)); put("signing", Security.publicKeyB64()); put("encryption", HostedEnvelope.exportPublic(HostedEnvelope.generateRecipient())) }
        prefs.edit().putString("device_id", device).putString("root", root.toString()).putString("recipient", recipient).commit()
        try {
            try { runtime.freshRequest(); fail("Incomplete trust store must not be trusted") } catch (_: HostedSessionException) { }
            assertEquals(HostedSetup.Stage.RECOVERY, runtime.setupStage())
            val previous = database.readBytes()
            runtime.restartSetup()
            assertEquals(HostedSetup.Stage.SCAN, runtime.setupStage())
            assertFalse(prefs.contains("device_id"))
            assertTrue(account.signedIn())
            assertEquals(recipient, HostedEnvelope.exportPublic(keys.load(recipient).recipient))
            assertArrayEquals(previous, database.readBytes())
        } finally { runtime.setEnabled(false); account.signOut(); prefs.edit().clear().commit() }
    }

    @Test fun rootScreenHasNoExitArrowAndSettingsStillHasBack() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        assertFalse(context.getSharedPreferences("orion_hosted", 0).contains("device_id"))
        AppPolicy.acknowledge(context)
        fun all(view: View): List<View> = listOf(view) + if (view is ViewGroup) (0 until view.childCount).flatMap { all(view.getChildAt(it)) } else emptyList()
        ActivityScenario.launch(HostedActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                assertFalse(all(activity.window.decorView).any { it.contentDescription == "Back" })
                HostedActivity::class.java.getDeclaredField("settingsPage").apply { isAccessible = true }.setBoolean(activity, true)
                HostedActivity::class.java.getDeclaredMethod("render").apply { isAccessible = true }.invoke(activity)
                val back = all(activity.window.decorView).single { it.contentDescription == "Back" }
                back.performClick()
                assertFalse(activity.isFinishing)
                assertFalse(all(activity.window.decorView).any { it.contentDescription == "Back" })
            }
        }
    }
}
