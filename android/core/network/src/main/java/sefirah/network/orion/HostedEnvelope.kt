package sefirah.network.orion

import com.google.crypto.tink.HybridDecrypt
import com.google.crypto.tink.HybridEncrypt
import com.google.crypto.tink.KeysetHandle
import com.google.crypto.tink.RegistryConfiguration
import com.google.crypto.tink.TinkProtoKeysetFormat
import com.google.crypto.tink.hybrid.HybridConfig
import com.google.crypto.tink.proto.HpkeAead
import com.google.crypto.tink.proto.HpkeKdf
import com.google.crypto.tink.proto.HpkeKem
import com.google.crypto.tink.proto.HpkePublicKey
import com.google.crypto.tink.proto.KeyData
import com.google.crypto.tink.proto.KeyStatusType
import com.google.crypto.tink.proto.Keyset
import com.google.crypto.tink.proto.OutputPrefixType
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.nio.charset.StandardCharsets
import java.security.AlgorithmParameters
import java.security.PrivateKey
import java.security.PublicKey
import java.security.Signature
import java.security.interfaces.ECKey
import java.security.spec.ECGenParameterSpec
import java.security.spec.ECParameterSpec
import java.util.Base64
import java.util.UUID

/** Safe error: never includes key material, ciphertext or decrypted content. */
class HostedEnvelopeException : IllegalArgumentException("Cannot process encrypted envelope.")

/**
 * Client-only HPKE envelope foundation matching Python hosted_crypto.py.
 *
 * No persistence, Android services, trust enrollment or application actions are
 * implemented here. The caller must verify a pinned signed roster and enforce
 * destination, roster generation, expiry and replay before consuming content.
 * Static recipient keys do not provide forward secrecy for retained ciphertext.
 */
object HostedEnvelope {
    const val MAX_CIPHERTEXT_BYTES = 49_152
    const val MAX_PLAINTEXT_BYTES = 24_000
    const val MAX_PUBLIC_KEYSET_BYTES = 1_024
    private const val MAX_SAFE_INTEGER = 9_007_199_254_740_991L
    private val signDomain = "Orion/hosted-envelope/signature/v1\u0000".toByteArray(StandardCharsets.US_ASCII)
    private val contextDomain = "Orion/hosted-envelope/context/v1\u0000".toByteArray(StandardCharsets.US_ASCII)
    private val integer = Regex("-?(0|[1-9][0-9]*)")
    private val device = Regex("dev_[a-f0-9]{32}")
    private val digest = Regex("[a-f0-9]{64}")
    private val headerKeys = setOf("protocol_version", "deployment_id", "roster_version", "roster_hash", "id", "source", "target", "expires_at")
    private val p256: ECParameterSpec = AlgorithmParameters.getInstance("EC").apply {
        init(ECGenParameterSpec("secp256r1"))
    }.getParameterSpec(ECParameterSpec::class.java)
    private val json = Json { isLenient = false; allowSpecialFloatingPointValues = false }

    init {
        HybridConfig.register()
    }

    private inline fun <T> safe(action: () -> T): T = try {
        action()
    } catch (_: Exception) {
        throw HostedEnvelopeException()
    }

    private fun requireValid(condition: Boolean) {
        if (!condition) throw HostedEnvelopeException()
    }

    /** Same ASCII escaping and Unicode code-point key order as Python JSON. */
    fun canonical(value: JsonElement): ByteArray = safe {
        var nodes = 8_192
        var strings = MAX_CIPHERTEXT_BYTES
        val output = StringBuilder()
        fun string(value: String) {
            requireValid(value.length <= MAX_CIPHERTEXT_BYTES * 2)
            strings -= value.codePointCount(0, value.length)
            requireValid(strings >= 0)
            output.append('"')
            var offset = 0
            while (offset < value.length) {
                val c = value[offset]
                if (Character.isHighSurrogate(c)) {
                    requireValid(offset + 1 < value.length && Character.isLowSurrogate(value[offset + 1]))
                    output.append("\\u").append(c.code.toString(16).padStart(4, '0'))
                    output.append("\\u").append(value[++offset].code.toString(16).padStart(4, '0'))
                } else {
                    requireValid(!Character.isLowSurrogate(c))
                    when (c) {
                        '"' -> output.append("\\\"")
                        '\\' -> output.append("\\\\")
                        '\b' -> output.append("\\b")
                        '\u000c' -> output.append("\\f")
                        '\n' -> output.append("\\n")
                        '\r' -> output.append("\\r")
                        '\t' -> output.append("\\t")
                        else -> if (c.code < 32 || c.code >= 127) {
                            output.append("\\u").append(c.code.toString(16).padStart(4, '0'))
                        } else output.append(c)
                    }
                }
                offset++
                requireValid(output.length <= MAX_CIPHERTEXT_BYTES)
            }
            output.append('"')
        }
        fun visit(item: JsonElement, depth: Int) {
            requireValid(--nodes >= 0 && depth <= 16)
            when (item) {
                JsonNull -> output.append("null")
                is JsonPrimitive -> if (item.isString) string(item.content) else {
                    when (item.content) {
                        "true", "false" -> output.append(item.content)
                        else -> output.append(number(item).toString())
                    }
                }
                is JsonArray -> {
                    requireValid(item.size <= nodes)
                    output.append('[')
                    item.forEachIndexed { index, child ->
                        if (index > 0) output.append(',')
                        visit(child, depth + 1)
                    }
                    output.append(']')
                }
                is JsonObject -> {
                    requireValid(item.size <= nodes / 2)
                    output.append('{')
                    item.keys.sortedWith(::compareCodePoints).forEachIndexed { index, key ->
                        if (index > 0) output.append(',')
                        requireValid(--nodes >= 0 && depth + 1 <= 16)
                        string(key)
                        output.append(':')
                        visit(item.getValue(key), depth + 1)
                    }
                    output.append('}')
                }
            }
            requireValid(output.length <= MAX_CIPHERTEXT_BYTES)
        }
        visit(value, 0)
        output.toString().toByteArray(StandardCharsets.US_ASCII)
    }

    private fun compareCodePoints(left: String, right: String): Int {
        var a = 0
        var b = 0
        while (a < left.length && b < right.length) {
            val x = left.codePointAt(a)
            val y = right.codePointAt(b)
            if (x != y) return x.compareTo(y)
            a += Character.charCount(x)
            b += Character.charCount(y)
        }
        return (left.length - a).compareTo(right.length - b)
    }

    private fun number(value: JsonElement?): Long {
        requireValid(value is JsonPrimitive && value !is JsonNull && !value.isString && integer.matches(value.content))
        val result = (value as JsonPrimitive).content.toLong()
        requireValid(result in -MAX_SAFE_INTEGER..MAX_SAFE_INTEGER)
        return result
    }

    private fun text(value: JsonElement?): String {
        requireValid(value is JsonPrimitive && value.isString)
        return (value as JsonPrimitive).content
    }

    fun validateHeader(header: JsonObject) = safe {
        requireValid(header.keys == headerKeys && number(header["protocol_version"]) == 1L)
        for (name in listOf("deployment_id", "id")) {
            val value = text(header[name])
            requireValid(value.length == 36 && UUID.fromString(value).toString() == value)
        }
        requireValid(digest.matches(text(header["roster_hash"])))
        requireValid(device.matches(text(header["source"])) && device.matches(text(header["target"])))
        requireValid(number(header["roster_version"]) in 1..MAX_SAFE_INTEGER)
        requireValid(number(header["expires_at"]) in 1..253_402_300_799L)
    }

    private fun decode(value: String, maximum: Int): ByteArray {
        requireValid(value.isNotEmpty() && value.length <= 4 * ((maximum + 2) / 3))
        val raw = Base64.getDecoder().decode(value)
        requireValid(raw.size <= maximum && Base64.getEncoder().encodeToString(raw) == value)
        return raw
    }

    private fun checkPublic(serialized: ByteArray): KeysetHandle {
        requireValid(serialized.isNotEmpty() && serialized.size <= MAX_PUBLIC_KEYSET_BYTES)
        val keys = Keyset.parseFrom(serialized)
        requireValid(keys.keyCount == 1)
        val entry = keys.getKey(0)
        requireValid(entry.status == KeyStatusType.ENABLED && entry.keyId == keys.primaryKeyId &&
            entry.outputPrefixType == OutputPrefixType.TINK &&
            entry.keyData.keyMaterialType == KeyData.KeyMaterialType.ASYMMETRIC_PUBLIC &&
            entry.keyData.typeUrl == "type.googleapis.com/google.crypto.tink.HpkePublicKey")
        val key = HpkePublicKey.parseFrom(entry.keyData.value)
        requireValid(key.version == 0 && key.publicKey.size() == 32 &&
            key.params.kem == HpkeKem.DHKEM_X25519_HKDF_SHA256 &&
            key.params.kdf == HpkeKdf.HKDF_SHA256 && key.params.aead == HpkeAead.AES_256_GCM)
        return TinkProtoKeysetFormat.parseKeysetWithoutSecret(serialized).also {
            it.getPrimitive(RegistryConfiguration.get(), HybridEncrypt::class.java)
        }
    }

    fun generateRecipient(): KeysetHandle = safe {
        KeysetHandle.newBuilder().addEntry(KeysetHandle.generateEntryFromParametersName(
            "DHKEM_X25519_HKDF_SHA256_HKDF_SHA256_AES_256_GCM"
        ).withRandomId().makePrimary()).build()
    }

    /** Only public keysets can be exported through the production API. */
    fun exportPublic(handle: KeysetHandle): String = safe {
        val raw = try {
            TinkProtoKeysetFormat.serializeKeysetWithoutSecret(handle)
        } catch (_: Exception) {
            TinkProtoKeysetFormat.serializeKeysetWithoutSecret(handle.publicKeysetHandle)
        }
        checkPublic(raw)
        Base64.getEncoder().encodeToString(raw)
    }

    fun readPublic(value: String): KeysetHandle = safe { checkPublic(decode(value, MAX_PUBLIC_KEYSET_BYTES)) }

    private fun checkSigningKey(key: java.security.Key) {
        requireValid(key.algorithm == "EC" && key is ECKey)
        val params = (key as ECKey).params
        requireValid(params.curve == p256.curve && params.generator == p256.generator &&
            params.order == p256.order && params.cofactor == p256.cofactor)
    }

    fun seal(recipient: String, signingKey: PrivateKey, header: JsonObject, payload: JsonObject): String =
        seal(readPublic(recipient), signingKey, header, payload)

    fun seal(recipient: KeysetHandle, signingKey: PrivateKey, header: JsonObject, payload: JsonObject): String = safe {
        validateHeader(header)
        checkSigningKey(signingKey)
        val public = checkPublic(TinkProtoKeysetFormat.serializeKeysetWithoutSecret(recipient))
        requireValid(canonical(payload).size <= MAX_PLAINTEXT_BYTES)
        val signature = Signature.getInstance("SHA256withECDSA").run {
            initSign(signingKey)
            update(signDomain + canonical(JsonObject(mapOf("header" to header, "payload" to payload))))
            sign()
        }
        val plaintext = canonical(JsonObject(mapOf("payload" to payload,
            "signature" to JsonPrimitive(Base64.getEncoder().encodeToString(signature)))))
        requireValid(plaintext.size <= MAX_PLAINTEXT_BYTES)
        val ciphertext = public.getPrimitive(RegistryConfiguration.get(), HybridEncrypt::class.java)
            .encrypt(plaintext, contextDomain + canonical(header))
        requireValid(ciphertext.size <= MAX_CIPHERTEXT_BYTES)
        Base64.getEncoder().encodeToString(ciphertext)
    }

    private fun checkJsonNesting(plaintext: ByteArray) {
        var depth = 0
        var quoted = false
        var escaped = false
        for (byte in plaintext) {
            val c = byte.toInt()
            requireValid(c in 0..127) // Signed plaintext uses ASCII JSON only.
            if (quoted) {
                if (escaped) escaped = false else when (c) {
                    92 -> escaped = true
                    34 -> quoted = false
                }
            } else when (c) {
                34 -> quoted = true
                91, 123 -> requireValid(++depth <= 17)
                93, 125 -> requireValid(--depth >= 0)
            }
        }
        requireValid(depth == 0 && !quoted)
    }

    fun openEnvelope(recipient: KeysetHandle, sender: PublicKey, header: JsonObject, ciphertext: String): JsonObject = safe {
        validateHeader(header)
        checkSigningKey(sender)
        val plaintext = recipient.getPrimitive(RegistryConfiguration.get(), HybridDecrypt::class.java)
            .decrypt(decode(ciphertext, MAX_CIPHERTEXT_BYTES), contextDomain + canonical(header))
        requireValid(plaintext.size <= MAX_PLAINTEXT_BYTES)
        checkJsonNesting(plaintext)
        val envelope = json.parseToJsonElement(String(plaintext, StandardCharsets.UTF_8)) as? JsonObject
            ?: throw HostedEnvelopeException()
        requireValid(envelope.keys == setOf("payload", "signature") && canonical(envelope).contentEquals(plaintext))
        val payload = envelope["payload"] as? JsonObject ?: throw HostedEnvelopeException()
        val signature = decode(text(envelope["signature"]), 80)
        requireValid(Signature.getInstance("SHA256withECDSA").run {
            initVerify(sender)
            update(signDomain + canonical(JsonObject(mapOf("header" to header, "payload" to payload))))
            verify(signature)
        })
        payload
    }
}
