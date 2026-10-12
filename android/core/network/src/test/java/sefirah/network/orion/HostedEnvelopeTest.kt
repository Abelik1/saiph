package sefirah.network.orion

import com.google.crypto.tink.HybridEncrypt
import com.google.crypto.tink.InsecureSecretKeyAccess
import com.google.crypto.tink.RegistryConfiguration
import com.google.crypto.tink.TinkProtoKeysetFormat
import com.google.crypto.tink.proto.HpkeAead
import com.google.crypto.tink.proto.HpkePublicKey
import com.google.crypto.tink.proto.KeyStatusType
import com.google.crypto.tink.proto.Keyset
import com.google.crypto.tink.proto.OutputPrefixType
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.nio.charset.StandardCharsets
import java.nio.file.Files
import java.nio.file.Path
import java.security.KeyFactory
import java.security.KeyPair
import java.security.KeyPairGenerator
import java.security.spec.ECGenParameterSpec
import java.security.spec.PKCS8EncodedKeySpec
import java.security.spec.X509EncodedKeySpec
import java.util.Base64
import java.util.UUID

class HostedEnvelopeTest {
    private fun signing(curve: String = "secp256r1"): KeyPair = KeyPairGenerator.getInstance("EC").run {
        initialize(ECGenParameterSpec(curve))
        generateKeyPair()
    }

    private fun header() = buildJsonObject {
        put("protocol_version", 1)
        put("deployment_id", UUID.randomUUID().toString())
        put("roster_version", 1)
        put("roster_hash", "a".repeat(64))
        put("id", UUID.randomUUID().toString())
        put("source", "dev_" + "1".repeat(32))
        put("target", "dev_" + "2".repeat(32))
        put("expires_at", 1_900_000_000)
    }

    private fun rejected(action: () -> Unit) {
        try {
            action()
            fail("Expected safe rejection")
        } catch (error: HostedEnvelopeException) {
            assertEquals("Cannot process encrypted envelope.", error.message)
            assertNull(error.cause)
        }
    }

    @Test fun roundtripAndRandomization() {
        val keys = signing()
        val recipient = HostedEnvelope.generateRecipient()
        val public = HostedEnvelope.exportPublic(recipient)
        assertEquals(public, HostedEnvelope.exportPublic(HostedEnvelope.readPublic(public)))
        val payload = buildJsonObject {
            put("type", "clipboard.text")
            put("text", "synthetic private \u2603 \uD83D\uDE80")
            putJsonArray("details") { add(1); add(true); add(JsonNull) }
        }
        val header = header()
        val first = HostedEnvelope.seal(public, keys.private, header, payload)
        val second = HostedEnvelope.seal(HostedEnvelope.readPublic(public), keys.private, header, payload)
        assertNotEquals(first, second)
        assertFalse(String(Base64.getDecoder().decode(first), StandardCharsets.ISO_8859_1).contains("synthetic private"))
        assertEquals(payload, HostedEnvelope.openEnvelope(recipient, keys.public, header, first))
        assertEquals(payload, HostedEnvelope.openEnvelope(recipient, keys.public, JsonObject(header.entries.reversed().associate { it.toPair() }), second))
    }

    @Test fun everyHeaderBindingAndCiphertextAreAuthenticated() {
        val sender = signing()
        val recipient = HostedEnvelope.generateRecipient()
        val header = header()
        val payload = buildJsonObject { put("type", "test"); put("text", "synthetic-marker") }
        val ciphertext = HostedEnvelope.seal(HostedEnvelope.exportPublic(recipient), sender.private, header, payload)
        rejected { HostedEnvelope.openEnvelope(HostedEnvelope.generateRecipient(), sender.public, header, ciphertext) }
        rejected { HostedEnvelope.openEnvelope(recipient, signing().public, header, ciphertext) }
        val modified = Base64.getDecoder().decode(ciphertext)
        modified[modified.lastIndex] = (modified.last().toInt() xor 1).toByte()
        rejected { HostedEnvelope.openEnvelope(recipient, sender.public, header, Base64.getEncoder().encodeToString(modified)) }
        for (name in header.keys) {
            val changed = header.toMutableMap()
            changed[name] = when (name) {
                "protocol_version" -> JsonPrimitive(2)
                "roster_hash" -> JsonPrimitive("b".repeat(64))
                "id", "deployment_id" -> JsonPrimitive(UUID.randomUUID().toString())
                "source", "target" -> JsonPrimitive("dev_" + "3".repeat(32))
                else -> JsonPrimitive(header.getValue(name).jsonPrimitive.long + 1)
            }
            rejected { HostedEnvelope.openEnvelope(recipient, sender.public, JsonObject(changed), ciphertext) }
        }
    }

    @Test fun canonicalMatchesPythonIncludingUnicodeKeyOrder() {
        val value = buildJsonObject {
            put("z", 1)
            put("a", "\u2603\n\t\b\u000c\r\u007f/\"\\\uD83D\uDE80")
            put("\uD83D\uDE80", true)
            put("\uE000", false)
        }
        assertEquals("{\"a\":\"\\u2603\\n\\t\\b\\f\\r\\u007f/\\\"\\\\\\ud83d\\ude80\",\"z\":1,\"\\ue000\":false,\"\\ud83d\\ude80\":true}",
            String(HostedEnvelope.canonical(value), StandardCharsets.US_ASCII))
        for (bad in listOf(JsonPrimitive(1.0), JsonPrimitive(Double.NaN), JsonPrimitive(Double.POSITIVE_INFINITY),
            JsonPrimitive(9_007_199_254_740_992L), JsonPrimitive("\uD800"), JsonPrimitive("\uDC00"), JsonPrimitive("x".repeat(49_153)),
            JsonPrimitive("\u2603".repeat(9_000)), JsonArray(List(8_193) { JsonNull }))) {
            rejected { HostedEnvelope.canonical(bad) }
        }
        var deep: JsonElement = JsonNull
        repeat(18) { deep = JsonArray(listOf(deep)) }
        rejected { HostedEnvelope.canonical(deep) }
    }

    @Test fun invalidHeadersAndMalformedEncodings() {
        val header = header()
        val mutations = listOf("protocol_version" to JsonPrimitive(true), "protocol_version" to JsonPrimitive("1"),
            "roster_version" to JsonPrimitive(0), "expires_at" to JsonPrimitive(0), "expires_at" to JsonPrimitive(1.5),
            "source" to JsonPrimitive("dev_" + "A".repeat(32)), "roster_hash" to JsonPrimitive("G".repeat(64)),
            "id" to JsonPrimitive("ABCDEFAB-ABCD-ABCD-ABCD-ABCDEFABCDEF"))
        for ((key, value) in mutations) rejected { HostedEnvelope.validateHeader(JsonObject(header + (key to value))) }
        rejected { HostedEnvelope.validateHeader(JsonObject(header + ("extra" to JsonNull))) }
        rejected { HostedEnvelope.validateHeader(JsonObject(header - "id")) }
        for (bad in listOf("", " ", "@@@", "eA", "eB==", "eA==\n", "\u2603", Base64.getEncoder().encodeToString(ByteArray(1_025)))) {
            rejected { HostedEnvelope.readPublic(bad) }
        }
    }

    @Test fun strictPublicSuiteAndPrivateExportBoundary() {
        val recipient = HostedEnvelope.generateRecipient()
        val public = HostedEnvelope.exportPublic(recipient)
        val original = Keyset.parseFrom(Base64.getDecoder().decode(public))
        for (mutation in 0..8) {
            val keys = original.toBuilder()
            val entry = keys.getKey(0).toBuilder()
            when (mutation) {
                0 -> entry.status = KeyStatusType.DISABLED
                1 -> keys.primaryKeyId = keys.primaryKeyId xor 1
                2 -> entry.outputPrefixType = OutputPrefixType.RAW
                3 -> keys.addKey(entry.build())
                4 -> {
                    val hpke = HpkePublicKey.parseFrom(entry.keyData.value).toBuilder()
                    hpke.params = hpke.params.toBuilder().setAead(HpkeAead.AES_128_GCM).build()
                    entry.keyData = entry.keyData.toBuilder().setValue(hpke.build().toByteString()).build()
                }
                5 -> entry.keyData = entry.keyData.toBuilder().setTypeUrl("invalid").build()
                6 -> entry.keyData = entry.keyData.toBuilder().setKeyMaterialType(com.google.crypto.tink.proto.KeyData.KeyMaterialType.ASYMMETRIC_PRIVATE).build()
                7, 8 -> {
                    val hpke = HpkePublicKey.parseFrom(entry.keyData.value).toBuilder()
                    if (mutation == 7) hpke.version = 1 else hpke.publicKey = hpke.publicKey.substring(0, 31)
                    entry.keyData = entry.keyData.toBuilder().setValue(hpke.build().toByteString()).build()
                }
            }
            keys.setKey(0, entry)
            rejected { HostedEnvelope.readPublic(Base64.getEncoder().encodeToString(keys.build().toByteArray())) }
        }
        // Secret serialization exists only in this synthetic unit-test boundary.
        val secret = TinkProtoKeysetFormat.serializeKeyset(recipient, InsecureSecretKeyAccess.get(), RegistryConfiguration.get())
        rejected { HostedEnvelope.readPublic(Base64.getEncoder().encodeToString(secret)) }
        rejected { HostedEnvelope.seal(recipient, signing().private, header(), buildJsonObject {}) }
    }

    @Test fun boundsAndSigningCurve() {
        val recipient = HostedEnvelope.generateRecipient()
        val public = HostedEnvelope.exportPublic(recipient)
        val signer = signing()
        val header = header()
        rejected { HostedEnvelope.seal(public, signing("secp384r1").private, header, buildJsonObject {}) }
        rejected { HostedEnvelope.seal(public, signer.private, header, buildJsonObject { put("text", "x".repeat(24_000)) }) }
        val payload = buildJsonObject { put("text", "x".repeat(23_700)) }
        val ciphertext = HostedEnvelope.seal(public, signer.private, header, payload)
        assertEquals(payload, HostedEnvelope.openEnvelope(recipient, signer.public, header, ciphertext))
        rejected { HostedEnvelope.openEnvelope(recipient, signing("secp384r1").public, header, ciphertext) }
        rejected { HostedEnvelope.openEnvelope(recipient, signer.public, header, Base64.getEncoder().encodeToString(ByteArray(49_153))) }
    }

    @Test fun maliciousPublicSenderPlaintextsAreRejected() {
        val recipient = HostedEnvelope.generateRecipient()
        val encryptor = HostedEnvelope.readPublic(HostedEnvelope.exportPublic(recipient))
            .getPrimitive(RegistryConfiguration.get(), HybridEncrypt::class.java)
        val sender = signing()
        val header = header()
        val context = "Orion/hosted-envelope/context/v1\u0000".toByteArray(StandardCharsets.US_ASCII) + HostedEnvelope.canonical(header)
        for (raw in listOf("not-json", "{\"payload\":{},\"payload\":{},\"signature\":\"eA==\"}",
            "{\"payload\":{},\"signature\":\"eA==\"}", "{\"payload\":{\"x\":NaN},\"signature\":\"eA==\"}",
            "{\"payload\":[],\"signature\":\"eA==\"}", "x".repeat(24_001),
            "[".repeat(2_000) + "0" + "]".repeat(2_000),
            "{\"payload\":{\"text\":\"\u2603\"},\"signature\":\"eA==\"}")) {
            val ciphertext = Base64.getEncoder().encodeToString(encryptor.encrypt(raw.toByteArray(StandardCharsets.UTF_8), context))
            rejected { HostedEnvelope.openEnvelope(recipient, sender.public, header, ciphertext) }
        }
    }

    @Test fun optionalPythonInteropFixture() {
        val path = System.getenv("ORION_HPKE_FIXTURE")
        assumeTrue("Optional isolated Python/Kotlin interoperability fixture", !path.isNullOrBlank())
        val fixture = Json.parseToJsonElement(Files.readString(Path.of(path!!))).jsonObject
        fun text(name: String) = fixture.getValue(name).jsonPrimitive.content
        // These imports are TEST ONLY; never persist/export real recipient keys.
        val recipient = TinkProtoKeysetFormat.parseKeyset(Base64.getDecoder().decode(text("python_recipient_private_b64")),
            InsecureSecretKeyAccess.get(), RegistryConfiguration.get())
        val factory = KeyFactory.getInstance("EC")
        val signingPrivate = factory.generatePrivate(PKCS8EncodedKeySpec(Base64.getDecoder().decode(text("signing_private_pkcs8_b64"))))
        val signingPublic = factory.generatePublic(X509EncodedKeySpec(Base64.getDecoder().decode(text("signing_public_spki_b64"))))
        val header = fixture.getValue("header").jsonObject
        val payload = fixture.getValue("payload").jsonObject
        assertEquals(text("python_recipient_public_b64"), HostedEnvelope.exportPublic(recipient))
        assertEquals(payload, HostedEnvelope.openEnvelope(recipient, signingPublic, header, text("python_ciphertext")))
        val ciphertext = HostedEnvelope.seal(text("python_recipient_public_b64"), signingPrivate, header, payload)
        val output = buildJsonObject {
            put("header", header)
            put("payload", payload)
            put("kotlin_ciphertext", ciphertext)
            put("recipient_public_b64", HostedEnvelope.exportPublic(recipient))
            put("signing_public_spki_b64", text("signing_public_spki_b64"))
        }
        Files.writeString(Path.of(text("output_path")), output.toString())
    }
}
