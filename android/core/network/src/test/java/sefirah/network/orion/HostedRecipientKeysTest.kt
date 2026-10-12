package sefirah.network.orion

import com.google.crypto.tink.Aead
import com.google.crypto.tink.InsecureSecretKeyAccess
import com.google.crypto.tink.KeysetHandle
import com.google.crypto.tink.RegistryConfiguration
import com.google.crypto.tink.TinkProtoKeysetFormat
import com.google.crypto.tink.aead.AeadConfig
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.Assert.*
import org.junit.Test
import java.security.KeyPairGenerator
import java.security.spec.ECGenParameterSpec
import java.util.UUID

class HostedRecipientKeysTest {
    private val deviceId = "dev_" + "1".repeat(32)
    private val unusedPin get() = HostedEnvelope.exportPublic(HostedEnvelope.generateRecipient())
    private fun pin(value: HostedRecipientMaterial) = HostedEnvelope.exportPublic(value.recipient)
    private fun store(deployment: String, backend: MemoryBackend, device: String = deviceId) =
        HostedRecipientKeys.forTests(deployment, device, backend)

    private class MemoryBackend : HostedRecipientKeys.Backend {
        var intent: ByteArray? = null
        var encrypted: ByteArray? = null
        var wrapping: Aead? = null
        var masterCreates = 0
        var markerCreates = 0
        var writes = 0
        var masterUnavailable = false
        var masterCreationFails = false
        var writesFail = false
        var identityUnavailable = false
        var identity = identity()

        companion object {
            fun identity(curve: String = "secp256r1"): HostedRecipientKeys.SigningIdentity =
                KeyPairGenerator.getInstance("EC").run {
                    initialize(ECGenParameterSpec(curve))
                    generateKeyPair().let { HostedRecipientKeys.SigningIdentity(it.private, it.public) }
                }
            fun aead(): Aead {
                AeadConfig.register()
                return KeysetHandle.newBuilder().addEntry(KeysetHandle.generateEntryFromParametersName("AES256_GCM")
                    .withRandomId().makePrimary()).build().getPrimitive(RegistryConfiguration.get(), Aead::class.java)
            }
        }

        override fun <T> exclusively(action: () -> T): T = synchronized(this) { action() }
        override fun marker() = intent?.copyOf()
        override fun ciphertext() = encrypted?.copyOf()
        override fun hasMaster(): Boolean {
            if (masterUnavailable) error("synthetic sensitive provider detail")
            return wrapping != null
        }
        override fun signingIdentity(): HostedRecipientKeys.SigningIdentity {
            if (identityUnavailable) error("synthetic sensitive signing detail")
            return identity
        }
        override fun createMarker() {
            check(intent == null)
            markerCreates++
            intent = "ORION_HOSTED_RECIPIENT_V1\n".toByteArray(Charsets.US_ASCII)
        }
        override fun createMaster() {
            masterCreates++
            if (masterCreationFails) error("synthetic sensitive provider detail")
            check(wrapping == null)
            wrapping = aead()
        }
        override fun master(): Aead {
            if (masterUnavailable) error("synthetic sensitive provider detail")
            return wrapping ?: error("synthetic missing master")
        }
        override fun saveCiphertext(value: ByteArray) {
            writes++
            if (writesFail) error("synthetic write detail")
            check(encrypted == null)
            encrypted = value.copyOf()
        }
    }

    private fun rejected(action: () -> Unit) {
        try { action(); fail("Expected fail-closed rejection") } catch (error: HostedKeyStorageException) {
            assertEquals("Protected Saiph keys are unavailable. Device approval may need recovery.", error.message)
            assertNull(error.cause)
        }
    }

    @Test fun encryptedCreationAndReloadPreserveRecipientAndExistingIdentity() {
        val backend = MemoryBackend()
        val deployment = UUID.randomUUID().toString()
        val store = store(deployment, backend)
        val created = store.create()
        val loaded = store(deployment, backend).load(pin(created))
        assertEquals(HostedEnvelope.exportPublic(created.recipient), HostedEnvelope.exportPublic(loaded.recipient))
        assertSame(backend.identity.private, created.signingPrivate)
        assertSame(backend.identity.public, loaded.signingPublic)
        assertEquals(1, backend.masterCreates)
        assertEquals(1, backend.markerCreates)
        assertEquals(1, backend.writes)
        // Real Tink encrypted-keyset serialization, not a mocked cipher.
        val rawPrivate = TinkProtoKeysetFormat.serializeKeyset(created.recipient, InsecureSecretKeyAccess.get(), RegistryConfiguration.get())
        assertFalse(backend.encrypted!!.contentEquals(rawPrivate))
        rejected {
            // Plaintext keysets are rejected rather than migrated or accepted.
            backend.encrypted = rawPrivate
            store.load(pin(created))
        }
    }

    @Test fun loadingMissingStateNeverCreatesAnything() {
        val backend = MemoryBackend()
        val store = store(UUID.randomUUID().toString(), backend)
        rejected { store.load(unusedPin) }
        assertEquals(0, backend.masterCreates)
        assertEquals(0, backend.markerCreates)
        assertEquals(0, backend.writes)
    }

    @Test fun missingOrUnusableKeystorePreservesEvidenceAndNeverRecreates() {
        for (unavailable in listOf(false, true)) {
            val backend = MemoryBackend()
            val store = store(UUID.randomUUID().toString(), backend)
            val expected = pin(store.create())
            val saved = backend.encrypted!!.copyOf()
            if (unavailable) backend.masterUnavailable = true else backend.wrapping = null
            rejected { store.load(expected) }
            rejected { store.create() }
            assertArrayEquals(saved, backend.encrypted)
            assertEquals(1, backend.masterCreates)
            assertEquals(1, backend.writes)
        }
    }

    @Test fun failedMasterCreationLeavesTombstoneAndBlocksRetry() {
        val backend = MemoryBackend().apply { masterCreationFails = true }
        val store = store(UUID.randomUUID().toString(), backend)
        rejected { store.create() }
        assertNotNull(backend.intent)
        assertNull(backend.encrypted)
        backend.masterCreationFails = false
        rejected { store.create() }
        rejected { store.load(unusedPin) }
        assertEquals(1, backend.masterCreates)
        assertEquals(0, backend.writes)
    }

    @Test fun interruptedEncryptedWriteRequiresExplicitRecovery() {
        val backend = MemoryBackend().apply { writesFail = true }
        val store = store(UUID.randomUUID().toString(), backend)
        rejected { store.create() }
        assertNotNull(backend.intent)
        assertNotNull(backend.wrapping)
        assertNull(backend.encrypted)
        backend.writesFail = false
        rejected { store.create() }
        rejected { store.load(unusedPin) }
        assertEquals(1, backend.masterCreates)
        assertEquals(1, backend.writes)
    }

    @Test fun corruptionWrongMasterAndDeploymentBindingFailClosed() {
        for (mutation in 0..4) {
            val backend = MemoryBackend()
            val deployment = UUID.randomUUID().toString()
            val store = store(deployment, backend)
            val expected = pin(store.create())
            when (mutation) {
                0 -> backend.encrypted = backend.encrypted!!.copyOf().apply { this[lastIndex] = (last().toInt() xor 1).toByte() }
                1 -> backend.wrapping = MemoryBackend.aead()
                2 -> backend.intent = "wrong-marker".toByteArray()
                3 -> backend.encrypted = ByteArray(16_385)
                4 -> backend.intent = null
            }
            rejected { store.load(expected) }
            rejected { store.create() }
            assertEquals(1, backend.masterCreates)
            assertEquals(1, backend.writes)
        }
        val backend = MemoryBackend()
        val deployment = UUID.randomUUID().toString()
        val expected = pin(store(deployment, backend).create())
        rejected { store(UUID.randomUUID().toString(), backend).load(expected) }
        rejected { store(deployment, backend, "dev_" + "2".repeat(32)).load(expected) }
    }

    @Test fun replacingOrLosingExistingSigningIdentityDoesNotCreateAnIdentity() {
        val backend = MemoryBackend()
        val store = store(UUID.randomUUID().toString(), backend)
        val expected = pin(store.create())
        val original = backend.identity
        backend.identity = MemoryBackend.identity()
        rejected { store.load(expected) }
        backend.identity = HostedRecipientKeys.SigningIdentity(original.private, backend.identity.public)
        rejected { store.load(expected) }
        backend.identityUnavailable = true
        rejected { store.load(expected) }
        assertEquals(1, backend.masterCreates)
    }

    @Test fun missingSigningIdentityPreventsFirstCreation() {
        for (invalid in listOf("missing", "wrong-curve")) {
            val backend = MemoryBackend()
            if (invalid == "missing") backend.identityUnavailable = true else backend.identity = MemoryBackend.identity("secp384r1")
            rejected { store(UUID.randomUUID().toString(), backend).create() }
            assertEquals(0, backend.masterCreates)
            assertNull(backend.intent)
            assertNull(backend.encrypted)
        }
    }

    @Test fun preexistingMasterWithoutFilesPreventsSilentNewRecipient() {
        val backend = MemoryBackend().apply { wrapping = MemoryBackend.aead() }
        val store = store(UUID.randomUUID().toString(), backend)
        rejected { store.create() }
        rejected { store.load(unusedPin) }
        assertEquals(0, backend.masterCreates)
        assertEquals(0, backend.markerCreates)
    }

    @Test fun publicOnlyOrWrongSuiteEncryptedKeysetIsRejected() {
        val backend = MemoryBackend()
        val deployment = UUID.randomUUID().toString()
        val store = store(deployment, backend)
        val created = store.create()
        val expected = pin(created)
        val aad = "Orion/hosted-recipient-storage/v1\u0000".toByteArray(Charsets.US_ASCII) + HostedEnvelope.canonical(buildJsonObject {
            put("deployment_id", deployment)
            put("device_id", deviceId)
            put("signing_key", java.util.Base64.getEncoder().encodeToString(backend.identity.public.encoded))
            put("recipient_key", expected)
        })
        val candidates = listOf(created.recipient.publicKeysetHandle,
            KeysetHandle.newBuilder().addEntry(KeysetHandle.generateEntryFromParametersName("AES256_GCM")
                .withRandomId().makePrimary()).build())
        for (handle in candidates) {
            backend.encrypted = TinkProtoKeysetFormat.serializeEncryptedKeyset(handle, backend.master(), aad, RegistryConfiguration.get())
            rejected { store.load(expected) }
        }
    }

    @Test fun swappedValidRecipientAndWrongTrustedPinAreRejected() {
        val backend = MemoryBackend()
        val deployment = UUID.randomUUID().toString()
        val store = store(deployment, backend)
        val expected = pin(store.create())
        rejected { store.load(unusedPin) }
        rejected { store.load("invalid-public-key") }
        val replacement = HostedEnvelope.generateRecipient()
        val aad = "Orion/hosted-recipient-storage/v1\u0000".toByteArray(Charsets.US_ASCII) + HostedEnvelope.canonical(buildJsonObject {
            put("deployment_id", deployment)
            put("device_id", deviceId)
            put("signing_key", java.util.Base64.getEncoder().encodeToString(backend.identity.public.encoded))
            put("recipient_key", expected)
        })
        // Even a valid recipient encrypted with the correct wrapping key and
        // expected AAD cannot replace the trusted enrolled recipient.
        backend.encrypted = TinkProtoKeysetFormat.serializeEncryptedKeyset(replacement, backend.master(), aad, RegistryConfiguration.get())
        rejected { store.load(expected) }
        assertEquals(1, backend.masterCreates)
        assertEquals(1, backend.writes)
    }
}
