// SPDX-License-Identifier: GPL-3.0-only
package sefirah.network.orion

import com.google.crypto.tink.*
import com.google.crypto.tink.streamingaead.StreamingAeadConfig
import com.google.crypto.tink.streamingaead.StreamingAeadKeyTemplates
import com.google.crypto.tink.proto.*
import kotlinx.serialization.json.*
import java.io.*
import java.util.Base64
import java.util.UUID

/** The same Tink streaming suite and binding as desktop hosted_files.py. */
object HostedAttachments {
    private const val LIMIT = 20 * 1024 * 1024
    private val domain = "Orion hosted attachment v1\u0000".toByteArray(Charsets.US_ASCII)
    private fun name(value: String): String {
        check(value.length in 1..255 && value !in listOf(".", "..") && value.last() !in " ." && value.none { it.code < 32 || it in "/\\:*?\"<>|" })
        check(!Regex("(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])").matches(value.substringBefore('.')))
        return value
    }
    private fun bounded(input: InputStream, maximum: Int): ByteArray {
        val output = ByteArrayOutputStream(); val buffer = ByteArray(65536)
        while (true) { val count = input.read(buffer); if (count < 0) break; check(output.size() + count <= maximum); output.write(buffer, 0, count) }
        return output.toByteArray()
    }
    class Prepared internal constructor(val descriptor: JsonObject, val envelope: JsonObject, internal val encrypted: ByteArray)
    /** [wrap] puts the file manifest inside a request's answer, such as `sms.attachment.original`. */
    fun send(session: HostedSession, transport: HostedHttpTransport, input: InputStream, filename: String, mime: String, target: String = session.root.deviceId, photo: String? = null, request: String? = null, wrap: ((JsonObject) -> JsonObject)? = null, authorize: () -> Unit = {}) {
        upload(transport, prepare(session, input, filename, mime, target, photo, request, wrap = wrap, authorize = authorize), authorize)
    }
    fun prepare(session: HostedSession, input: InputStream, filename: String, mime: String, target: String = session.root.deviceId, photo: String? = null, request: String? = null, kind: String = "file", ttlSeconds: Int = 300, wrap: ((JsonObject) -> JsonObject)? = null, authorize: () -> Unit = {}): Prepared = HostedSession.guarded {
        authorize()
        check(kind in listOf("file", "photo", "clipboard.image") && ttlSeconds in 1..300)
        check(wrap == null || (kind == "file" && photo == null))
        if (kind == "clipboard.image") check(mime in HostedClipboardImages.extensions && photo == null && ttlSeconds <= 30)
        StreamingAeadConfig.register()
        val source = bounded(input, if (kind == "clipboard.image") HostedClipboardImages.MAX_BYTES else LIMIT - 4096)
        val checkpoint = session.pagingCheckpoint(); session.currentMembers().also { check(target in it) }
        val binding = buildJsonObject {
            put("protocol_version", 1); put("deployment_id", session.root.deploymentId); put("id", UUID.randomUUID().toString())
            put("roster_version", checkpoint.version); put("roster_hash", checkpoint.digest); put("source", session.deviceId)
            put("target", target); put("expires_at", System.currentTimeMillis() / 1000 + ttlSeconds)
        }
        val handle = KeysetHandle.generateNew(StreamingAeadKeyTemplates.AES256_GCM_HKDF_1MB)
        val primitive = handle.getPrimitive(RegistryConfiguration.get(), StreamingAead::class.java)
        val output = ByteArrayOutputStream()
        primitive.newEncryptingStream(output, domain + HostedEnvelope.canonical(binding)).use { it.write(source) }
        val encrypted = output.toByteArray(); check(encrypted.size in 1..LIMIT)
        val payload = buildJsonObject {
            put("type", "file.encrypted"); put("kind", kind); put("name", name(filename)); put("mime", mime)
            put("size", source.size); put("sha256", HostedSession.digest(source)); put("blob", binding)
            put("ciphertext_size", encrypted.size); put("ciphertext_sha256", HostedSession.digest(encrypted))
            put("keyset", Base64.getEncoder().encodeToString(TinkProtoKeysetFormat.serializeKeyset(handle, InsecureSecretKeyAccess.get())))
        }
        val wrapped = if (wrap != null) wrap(payload) else if (photo == null) payload else buildJsonObject {
            check(Regex("[1-9][0-9]{0,15}").matches(photo) && request != null && UUID.fromString(request).toString() == request)
            put("type", "photo.original"); put("photo_id", photo); put("request", request); put("file", payload)
        }
        val envelope = session.encrypt(target, wrapped, ttlSeconds)
        val id = binding.getValue("id").jsonPrimitive.content
        val descriptor = buildJsonObject {
            for (key in listOf("id", "target", "roster_version", "roster_hash", "expires_at")) put(key, binding.getValue(key))
            put("size", encrypted.size); put("sha256", HostedSession.digest(encrypted))
        }
        Prepared(descriptor, envelope, encrypted)
    }
    fun upload(transport: HostedHttpTransport, prepared: Prepared, authorize: () -> Unit = {}) = HostedSession.guarded {
        val descriptor = prepared.descriptor
        val id = descriptor.getValue("id").jsonPrimitive.content
        val encrypted = prepared.encrypted
        authorize(); check(transport.allocateBlob(descriptor)["accepted"] == JsonPrimitive(true))
        var offset = 0
        while (offset < encrypted.size) { authorize(); val end = minOf(offset + 32768, encrypted.size); check(transport.uploadChunk(id, offset / 32768, encrypted.copyOfRange(offset, end))["accepted"] == JsonPrimitive(true)); offset = end }
        authorize(); check(transport.completeBlob(id)["ready"] == JsonPrimitive(true))
        authorize()
        check(transport.publishEnvelope(prepared.envelope)["accepted"] == JsonPrimitive(true))
    }
    fun receive(session: HostedSession, transport: HostedHttpTransport, envelope: JsonObject, privateFolder: File): File = HostedSession.guarded {
        StreamingAeadConfig.register()
        val payload = session.authenticate(envelope)
        check(payload.keys == setOf("type", "kind", "name", "mime", "size", "sha256", "blob", "ciphertext_size", "ciphertext_sha256", "keyset"))
        check(payload["type"] == JsonPrimitive("file.encrypted") && payload["kind"]?.jsonPrimitive?.content in listOf("file", "photo", "clipboard.image"))
        name(payload.getValue("name").jsonPrimitive.content)
        check(Regex("[a-z0-9.+-]{1,63}/[a-z0-9.+-]{1,63}").matches(payload.getValue("mime").jsonPrimitive.content))
        val size = HostedSession.number(payload["size"]); val cipherSize = HostedSession.number(payload["ciphertext_size"])
        check(size in 0..(LIMIT - 4096).toLong() && cipherSize in 1..LIMIT.toLong())
        if (payload["kind"] == JsonPrimitive("clipboard.image")) check(size in 1..HostedClipboardImages.MAX_BYTES.toLong() && payload["mime"]?.jsonPrimitive?.content in HostedClipboardImages.extensions)
        val binding = payload.getValue("blob").jsonObject; val header = envelope.getValue("header").jsonObject
        check(binding.keys == setOf("protocol_version", "deployment_id", "id", "roster_version", "roster_hash", "source", "target", "expires_at"))
        for (key in listOf("protocol_version", "deployment_id", "roster_version", "roster_hash", "source", "target")) check(binding[key] == header[key])
        check(HostedSession.number(binding["expires_at"]) in (System.currentTimeMillis() / 1000 + 1)..(HostedSession.number(header["expires_at"]) + 1))
        val id = binding.getValue("id").jsonPrimitive.content; check(UUID.fromString(id).toString() == id)
        val encoded = payload.getValue("keyset").jsonPrimitive.content; check(encoded.length <= 2048)
        val raw = Base64.getDecoder().decode(encoded); check(raw.size in 1..1024 && Base64.getEncoder().encodeToString(raw) == encoded)
        val keyset = Keyset.parseFrom(raw); check(keyset.keyCount == 1)
        val entry = keyset.getKey(0)
        check(entry.keyId == keyset.primaryKeyId && entry.status == KeyStatusType.ENABLED && entry.outputPrefixType == OutputPrefixType.RAW &&
            entry.keyData.keyMaterialType == KeyData.KeyMaterialType.SYMMETRIC && entry.keyData.typeUrl == "type.googleapis.com/google.crypto.tink.AesGcmHkdfStreamingKey")
        val key = AesGcmHkdfStreamingKey.parseFrom(entry.keyData.value)
        check(key.version == 0 && key.keyValue.size() == 32 && key.params.derivedKeySize == 32 && key.params.hkdfHashType == HashType.SHA256 && key.params.ciphertextSegmentSize == 1048576)
        val encrypted = ByteArrayOutputStream()
        var index = 0
        while (encrypted.size() < cipherSize) { val chunk = transport.downloadChunk(id, index++); check(encrypted.size() + chunk.size <= cipherSize); encrypted.write(chunk) }
        val ciphertext = encrypted.toByteArray(); check(HostedSession.digest(ciphertext) == HostedSession.text(payload["ciphertext_sha256"]))
        val primitive = TinkProtoKeysetFormat.parseKeyset(raw, InsecureSecretKeyAccess.get()).getPrimitive(RegistryConfiguration.get(), StreamingAead::class.java)
        val plaintext = primitive.newDecryptingStream(ByteArrayInputStream(ciphertext), domain + HostedEnvelope.canonical(binding)).use { bounded(it, LIMIT - 4096) }
        check(plaintext.size.toLong() == size && HostedSession.digest(plaintext) == HostedSession.text(payload["sha256"]))
        session.authenticate(envelope)
        File.createTempFile("hosted-verified-", ".tmp", privateFolder).also { file ->
            try { FileOutputStream(file).use { it.write(plaintext); it.fd.sync() } } catch (failure: Exception) { file.delete(); throw failure }
        }
    }
}
