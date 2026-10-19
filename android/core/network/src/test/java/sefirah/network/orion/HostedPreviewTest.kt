// SPDX-License-Identifier: GPL-3.0-only
package sefirah.network.orion

import kotlinx.serialization.json.*
import okhttp3.Request
import okio.Buffer
import org.junit.Assert.*
import org.junit.Test
import java.io.ByteArrayInputStream
import java.nio.file.Files
import java.security.KeyPairGenerator
import java.security.Signature
import java.util.Base64
import java.util.UUID

class HostedPreviewTest {
    private val pair = KeyPairGenerator.getInstance("EC").apply { initialize(256) }.generateKeyPair()
    private val recipient = HostedEnvelope.generateRecipient()
    private val root = HostedRoot(UUID.randomUUID().toString(), "dev_" + "1".repeat(32), HostedSession.publicSigning(pair.public), HostedEnvelope.exportPublic(recipient))
    private fun sign(domain: String, data: JsonObject) = Base64.getEncoder().encodeToString(Signature.getInstance("SHA256withECDSA").run {
        initSign(pair.private); update((domain + "\u0000").toByteArray() + HostedEnvelope.canonical(data)); sign()
    })
    private fun rootCode(expiry: Long = System.currentTimeMillis() / 1000 + 300): String {
        val data = buildJsonObject { put("protocol_version", 1); put("deployment_id", root.deploymentId); put("root", root.member()); put("expires_at", expiry); put("nonce", "a".repeat(43)) }
        return "orion-root-v1:" + String(HostedEnvelope.canonical(buildJsonObject { put("data", data); put("signature", sign("Orion hosted root approval code v1", data)) }))
    }
    @Test fun rootPinRequiresFullFingerprintAndFreshSignedCanonicalCode() {
        val code = rootCode(); assertEquals(root, HostedApprovalCodes.inspect(code))
        assertEquals(root, HostedApprovalCodes.trust(code, HostedApprovalCodes.displayFingerprint(root.fingerprint())))
        assertTrue(runCatching { HostedApprovalCodes.trust(code, root.fingerprint().take(8)) }.isFailure)
        assertTrue(runCatching { HostedApprovalCodes.trust(code, "0".repeat(64)) }.isFailure)
        assertTrue(runCatching { HostedApprovalCodes.inspect(rootCode(1)) }.isFailure)
        assertTrue(runCatching { HostedApprovalCodes.inspect(code.replace("\"protocol_version\":1", "\"protocol_version\":2")) }.isFailure)
        assertTrue(runCatching { HostedApprovalCodes.inspect(code + " ") }.isFailure)
    }
    private class MemoryStore : HostedTrustStore {
        var state = HostedTrustSnapshot(HostedCheckpoint(0, ""), null, emptySet())
        override fun bind(binding: JsonObject) {}
        override fun checkpoint() = state.checkpoint
        override fun snapshot() = state
        override fun advance(expected: HostedTrustSnapshot, next: HostedTrustSnapshot) { check(state == expected); state = next }
        override fun acceptIncoming(envelope: JsonObject, expected: HostedCheckpoint, now: Long) = error("not used")
        override fun pendingIncoming(now: Long) = emptyList<JsonObject>()
    }
    @Test fun encryptedAttachmentRoundTripAndTamperRefusal() {
        val phoneKeys = KeyPairGenerator.getInstance("EC").apply { initialize(256) }.generateKeyPair()
        val phoneRecipient = HostedEnvelope.generateRecipient(); val phoneId = "dev_" + "2".repeat(32)
        val rootSession = HostedSession(root, root.deviceId, HostedRecipientMaterial(recipient, pair.private, pair.public), MemoryStore())
        val phoneSession = HostedSession(root, phoneId, HostedRecipientMaterial(phoneRecipient, phoneKeys.private, phoneKeys.public), MemoryStore())
        val members = listOf(root.member(), buildJsonObject { put("id", phoneId); put("signing_key", HostedSession.publicSigning(phoneKeys.public)); put("encryption_key", HostedEnvelope.exportPublic(phoneRecipient)) })
        val genesis = buildJsonObject { put("deployment_id", root.deploymentId); put("version", 1); put("previous_hash", JsonNull); put("expires_at", System.currentTimeMillis() / 1000 + 3600); put("members", JsonArray(listOf(root.member()))) }
        val second = buildJsonObject { put("deployment_id", root.deploymentId); put("version", 2); put("previous_hash", HostedSession.digest(HostedEnvelope.canonical(genesis))); put("expires_at", System.currentTimeMillis() / 1000 + 3600); put("members", JsonArray(members)) }
        val chain = JsonArray(listOf(genesis, second).map { value -> buildJsonObject { put("roster", value); put("signature", sign("Orion hosted roster v1", value)) } })
        rootSession.acceptChain(chain); phoneSession.acceptChain(chain)
        var event: JsonObject? = null; val chunks = mutableMapOf<Int, ByteArray>()
        val sender = HostedHttpTransport.Sender { request: Request, _: Int ->
            val buffer = Buffer(); request.body?.writeTo(buffer)
            val body = buffer.readByteArray().takeIf { it.isNotEmpty() }?.let(HostedHttpTransport::parse)
            val path = request.url.encodedPath
            val result = when {
                path.endsWith("/complete") -> buildJsonObject { put("ready", true) }
                "/chunks/" in path -> {
                    val index = path.substringAfterLast('/').toInt()
                    if (request.method == "POST") { chunks[index] = Base64.getDecoder().decode(body!!.getValue("data").jsonPrimitive.content); buildJsonObject { put("accepted", true) } }
                    else buildJsonObject { put("data", Base64.getEncoder().encodeToString(chunks.getValue(index))) }
                }
                path.endsWith("/events") -> { event = body; buildJsonObject { put("accepted", true) } }
                else -> buildJsonObject { put("accepted", true) }
            }
            HostedEnvelope.canonical(result)
        }
        val now = { System.currentTimeMillis() / 1000 }
        val phoneTransport = HostedHttpTransport.forTests("https://example.invalid", phoneSession, sender, now)
        val rootTransport = HostedHttpTransport.forTests("https://example.invalid", rootSession, sender, now)
        val source = ByteArray(100_000) { (it % 251).toByte() }
        HostedAttachments.send(phoneSession, phoneTransport, ByteArrayInputStream(source), "synthetic.bin", "application/octet-stream")
        val folder = Files.createTempDirectory("hosted-attachment-test").toFile()
        try {
            val saved = HostedAttachments.receive(rootSession, rootTransport, event!!, folder)
            assertArrayEquals(source, saved.readBytes()); saved.delete()
            chunks[0]!![100] = (chunks[0]!![100].toInt() xor 1).toByte()
            assertTrue(runCatching { HostedAttachments.receive(rootSession, rootTransport, event!!, folder) }.isFailure)
            assertEquals(0, folder.listFiles()!!.size)
            chunks.clear()
            val prepared = HostedAttachments.prepare(phoneSession, ByteArrayInputStream(source), "clipboard.png", "image/png",
                kind = "clipboard.image", ttlSeconds = 30)
            HostedAttachments.upload(phoneTransport, prepared)
            val firstEnvelope = event
            val firstChunks = chunks.mapValues { it.value.copyOf() }
            HostedAttachments.upload(phoneTransport, prepared)
            assertEquals(firstEnvelope, event)
            firstChunks.forEach { (index, bytes) -> assertArrayEquals(bytes, chunks[index]) }
            val manifest = rootSession.authenticate(event!!)
            assertEquals(JsonPrimitive("clipboard.image"), manifest["kind"])
            assertEquals(JsonPrimitive("image/png"), manifest["mime"])
            val imageBytes = HostedAttachments.receive(rootSession, rootTransport, event!!, folder)
            assertArrayEquals(source, imageBytes.readBytes()); imageBytes.delete()
            assertTrue(runCatching { HostedAttachments.prepare(phoneSession, ByteArrayInputStream(source), "clipboard.gif", "image/gif", kind = "clipboard.image", ttlSeconds = 30) }.isFailure)
            assertTrue(runCatching { HostedAttachments.prepare(phoneSession, ByteArrayInputStream(source), "clipboard.png", "image/png", kind = "clipboard.image", ttlSeconds = 31) }.isFailure)
        } finally { folder.deleteRecursively() }
    }
}
