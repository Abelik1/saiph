package sefirah.network.orion

import android.content.Context
import android.system.Os
import android.system.OsConstants
import com.google.crypto.tink.Aead
import com.google.crypto.tink.HybridDecrypt
import com.google.crypto.tink.KeysetHandle
import com.google.crypto.tink.RegistryConfiguration
import com.google.crypto.tink.TinkProtoKeysetFormat
import com.google.crypto.tink.integration.android.AndroidKeystore
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.io.File
import java.io.FileOutputStream
import java.io.RandomAccessFile
import java.security.AlgorithmParameters
import java.security.KeyStore
import java.security.PrivateKey
import java.security.PublicKey
import java.security.Signature
import java.security.interfaces.ECKey
import java.security.spec.ECGenParameterSpec
import java.security.spec.ECParameterSpec
import java.util.Base64
import java.util.UUID

class HostedKeyStorageException : IllegalStateException("Protected Saiph keys are unavailable. Device approval may need recovery.")

data class HostedRecipientMaterial(
    val recipient: KeysetHandle,
    val signingPrivate: PrivateKey,
    val signingPublic: PublicKey,
)

/**
 * Explicit, fail-closed storage of hosted recipient keys. Never creates or
 * replaces the existing P-256 identity. No plaintext serialization/fallback.
 * This foundation is not wired into an Android service or setup screen.
 */
class HostedRecipientKeys private constructor(
    private val deploymentId: String,
    private val deviceId: String,
    private val backend: Backend,
) {
    internal data class SigningIdentity(val private: PrivateKey, val public: PublicKey)

    internal interface Backend {
        fun <T> exclusively(action: () -> T): T
        fun marker(): ByteArray?
        fun ciphertext(): ByteArray?
        fun hasMaster(): Boolean
        fun signingIdentity(): SigningIdentity
        fun createMarker()
        fun createMaster()
        fun master(): Aead
        fun saveCiphertext(value: ByteArray)
    }

    companion object {
        private const val MAX_STORED_BYTES = 16_384
        private val markerBytes = "ORION_HOSTED_RECIPIENT_V1\n".toByteArray(Charsets.US_ASCII)
        private val processLock = Any()

        fun forDeployment(context: Context, deploymentId: String, deviceId: String): HostedRecipientKeys = safe {
            requireState(UUID.fromString(deploymentId).toString() == deploymentId)
            requireState(Regex("dev_[a-f0-9]{32}").matches(deviceId))
            val root = File(File(File(context.applicationContext.noBackupFilesDir.canonicalFile, "orion-hosted-keys-v1"), deploymentId), deviceId)
            HostedRecipientKeys(deploymentId, deviceId, NativeBackend(root, "orion_hosted_recipient_v1_${deploymentId}_$deviceId"))
        }

        internal fun forTests(deploymentId: String, deviceId: String, backend: Backend): HostedRecipientKeys = HostedRecipientKeys(deploymentId, deviceId, backend)

        private inline fun <T> safe(action: () -> T): T = try {
            action()
        } catch (_: Exception) {
            throw HostedKeyStorageException()
        }

        private fun requireState(value: Boolean) {
            if (!value) throw HostedKeyStorageException()
        }
    }

    /** User-initiated creation only. Any existing/partial state prevents creation. */
    fun create(): HostedRecipientMaterial = safe {
        backend.exclusively {
            requireState(backend.marker() == null && backend.ciphertext() == null && !backend.hasMaster())
            val signing = checkedIdentity()
            // Record intent before generating either key. Failure requires explicit
            // recovery rather than silently issuing a different device identity.
            backend.createMarker()
            backend.createMaster()
            requireState(backend.hasMaster())
            val handle = HostedEnvelope.generateRecipient()
            val expectedPublic = HostedEnvelope.exportPublic(handle)
            val encrypted = TinkProtoKeysetFormat.serializeEncryptedKeyset(
                handle, backend.master(), associatedData(signing, expectedPublic), RegistryConfiguration.get())
            requireState(encrypted.isNotEmpty() && encrypted.size <= MAX_STORED_BYTES)
            backend.saveCiphertext(encrypted)
            loadLocked(expectedPublic)
        }
    }

    /** Never creates master keys, recipient keys, signing keys, or missing state. */
    fun load(expectedRecipientPublic: String): HostedRecipientMaterial = safe {
        HostedEnvelope.readPublic(expectedRecipientPublic)
        backend.exclusively { loadLocked(expectedRecipientPublic) }
    }

    private fun loadLocked(expectedRecipientPublic: String): HostedRecipientMaterial {
        requireState(backend.marker()?.contentEquals(markerBytes) == true)
        val encrypted = backend.ciphertext() ?: throw HostedKeyStorageException()
        requireState(encrypted.isNotEmpty() && encrypted.size <= MAX_STORED_BYTES && backend.hasMaster())
        val signing = checkedIdentity()
        // This API only decrypts encrypted keysets: unlike AndroidKeysetManager,
        // it never attempts to interpret a decryption failure as a cleartext keyset.
        val handle = TinkProtoKeysetFormat.parseEncryptedKeyset(
            encrypted, backend.master(), associatedData(signing, expectedRecipientPublic), RegistryConfiguration.get())
        // The trusted approved roster supplies this pin; a merely valid stored
        // HPKE key is insufficient to restore an enrolled device identity.
        requireState(HostedEnvelope.exportPublic(handle) == expectedRecipientPublic)
        handle.getPrimitive(RegistryConfiguration.get(), HybridDecrypt::class.java)
        return HostedRecipientMaterial(handle, signing.private, signing.public)
    }

    private fun checkedIdentity(): SigningIdentity {
        val identity = backend.signingIdentity()
        val expected = AlgorithmParameters.getInstance("EC").apply {
            init(ECGenParameterSpec("secp256r1"))
        }.getParameterSpec(ECParameterSpec::class.java)
        for (key in listOf(identity.private, identity.public)) {
            requireState(key.algorithm == "EC" && key is ECKey)
            val actual = (key as ECKey).params
            requireState(actual.curve == expected.curve && actual.generator == expected.generator &&
                actual.order == expected.order && actual.cofactor == expected.cofactor)
        }
        val probe = "Orion hosted signing identity check v1\u0000".toByteArray(Charsets.US_ASCII)
        val proof = Signature.getInstance("SHA256withECDSA").run {
            initSign(identity.private); update(probe); sign()
        }
        requireState(Signature.getInstance("SHA256withECDSA").run {
            initVerify(identity.public); update(probe); verify(proof)
        })
        return identity
    }

    private fun associatedData(identity: SigningIdentity, expectedRecipientPublic: String) =
        "Orion/hosted-recipient-storage/v1\u0000".toByteArray(Charsets.US_ASCII) + HostedEnvelope.canonical(buildJsonObject {
            put("deployment_id", deploymentId)
            put("device_id", deviceId)
            put("signing_key", Base64.getEncoder().encodeToString(identity.public.encoded))
            put("recipient_key", expectedRecipientPublic)
        })

    private class NativeBackend(private val root: File, private val alias: String) : Backend {
        override fun <T> exclusively(action: () -> T): T = synchronized(processLock) {
            requireState(root.mkdirs() || root.isDirectory)
            requireState(root.canonicalFile == root.absoluteFile)
            ownerOnly(root, directory = true)
            val lock = child("store.lock")
            if (!lock.exists()) requireState(lock.createNewFile())
            ownerOnly(lock)
            RandomAccessFile(lock, "rw").use { file ->
                file.channel.lock().use { action() }
            }
        }

        private fun child(name: String): File = File(root, name).also {
            requireState(it.canonicalFile == it.absoluteFile)
        }

        private fun read(name: String): ByteArray? {
            val file = child(name)
            if (!file.exists()) return null
            requireState(file.isFile && file.length() in 1..MAX_STORED_BYTES)
            ownerOnly(file)
            return file.inputStream().use { input ->
                val output = java.io.ByteArrayOutputStream()
                val buffer = ByteArray(1024)
                while (true) {
                    val count = input.read(buffer)
                    if (count < 0) break
                    requireState(output.size() + count <= MAX_STORED_BYTES)
                    output.write(buffer, 0, count)
                }
                output.toByteArray()
            }
        }

        override fun marker() = read("created.marker")
        override fun ciphertext() = read("recipient.enc")
        override fun hasMaster(): Boolean = AndroidKeystore.hasKey(alias)

        override fun signingIdentity(): SigningIdentity {
            // Matches Security's existing alias. Deliberately do not invoke
            // ensureKey(): it recreates missing identities, which loading must not do.
            val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
            requireState(store.containsAlias("orion_device_p256"))
            val private = store.getKey("orion_device_p256", null) as? PrivateKey ?: throw HostedKeyStorageException()
            val public = store.getCertificate("orion_device_p256")?.publicKey ?: throw HostedKeyStorageException()
            return SigningIdentity(private, public)
        }

        override fun createMarker() = writeNew("created.marker", markerBytes)
        override fun createMaster() {
            // Tink's generate API overwrites aliases: explicitly refuse an existing
            // alias while holding our deployment/process lock.
            requireState(!AndroidKeystore.hasKey(alias))
            AndroidKeystore.generateNewAes256GcmKey(alias)
        }
        override fun master(): Aead = AndroidKeystore.getAead(alias)
        override fun saveCiphertext(value: ByteArray) = writeNew("recipient.enc", value)

        private fun writeNew(name: String, value: ByteArray) {
            val file = child(name)
            requireState(value.isNotEmpty() && value.size <= MAX_STORED_BYTES && file.createNewFile())
            ownerOnly(file)
            FileOutputStream(file).use { output -> output.write(value); output.fd.sync() }
            val directory = Os.open(root.absolutePath, OsConstants.O_RDONLY, 0)
            try { Os.fsync(directory) } finally { Os.close(directory) }
        }

        private fun ownerOnly(file: File, directory: Boolean = false) {
            requireState(file.setReadable(false, false) && file.setWritable(false, false) && file.setExecutable(false, false))
            requireState(file.setReadable(true, true) && file.setWritable(true, true))
            if (directory) requireState(file.setExecutable(true, true))
        }
    }
}
