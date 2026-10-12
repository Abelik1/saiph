package sefirah.network.orion

import com.google.crypto.tink.InsecureSecretKeyAccess
import com.google.crypto.tink.RegistryConfiguration
import com.google.crypto.tink.TinkProtoKeysetFormat
import kotlinx.serialization.json.*
import okhttp3.Request
import okio.Buffer
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.nio.file.Files
import java.nio.file.Path
import java.security.KeyFactory
import java.security.KeyPairGenerator
import java.security.Signature
import java.security.spec.ECGenParameterSpec
import java.security.spec.PKCS8EncodedKeySpec
import java.security.spec.X509EncodedKeySpec
import java.util.Base64
import java.util.UUID

internal class MemoryHostedTrust : HostedTrustStore {
    var binding: JsonObject? = null
    var checkpoint = HostedCheckpoint(0, "")
    var signedAnchor: JsonObject? = null
    var usedDeviceIds = emptySet<String>()
    val incoming = linkedMapOf<String, JsonObject>()
    var failCommit = false
    var beforeAdvance: (() -> Unit)? = null
    override fun bind(binding: JsonObject) {
        check(this.binding == null || this.binding == binding)
        this.binding = Json.parseToJsonElement(binding.toString()).jsonObject
    }
    override fun checkpoint() = checkpoint
    override fun snapshot() = HostedTrustSnapshot(checkpoint, signedAnchor?.let { Json.parseToJsonElement(it.toString()).jsonObject }, usedDeviceIds.toSet())
    override fun advance(expected: HostedTrustSnapshot, next: HostedTrustSnapshot) {
        beforeAdvance?.also { beforeAdvance = null; it() }
        check(!failCommit && snapshot() == expected && next.checkpoint.version >= checkpoint.version && next.usedDeviceIds.containsAll(usedDeviceIds))
        checkpoint = next.checkpoint
        signedAnchor = next.signedAnchor?.let { Json.parseToJsonElement(it.toString()).jsonObject }
        usedDeviceIds = next.usedDeviceIds.toSet()
    }
    override fun acceptIncoming(envelope: JsonObject, expected: HostedCheckpoint, now: Long): HostedInboxReceipt {
        check(checkpoint == expected)
        check(envelope.getValue("header").jsonObject.getValue("expires_at").jsonPrimitive.long > now)
        val id = envelope.getValue("header").jsonObject.getValue("id").jsonPrimitive.content
        val old = incoming[id]
        check(old == null || old == envelope)
        check(!failCommit)
        incoming[id] = Json.parseToJsonElement(envelope.toString()).jsonObject
        return HostedInboxReceipt(id, old != null)
    }
    override fun pendingIncoming(now: Long): List<JsonObject> {
        incoming.entries.removeAll { it.value.getValue("header").jsonObject.getValue("expires_at").jsonPrimitive.long <= now - 86_400 }
        return incoming.values.toList()
    }
}

class HostedSessionTest {
    private fun keys(): HostedRecipientMaterial {
        val pair = KeyPairGenerator.getInstance("EC").run { initialize(ECGenParameterSpec("secp256r1")); generateKeyPair() }
        return HostedRecipientMaterial(HostedEnvelope.generateRecipient(), pair.private, pair.public)
    }
    private fun member(id: String, keys: HostedRecipientMaterial) = buildJsonObject {
        put("id", id); put("signing_key", HostedSession.publicSigning(keys.signingPublic)); put("encryption_key", HostedEnvelope.exportPublic(keys.recipient))
    }
    private fun rejected(action: () -> Unit) {
        try { action(); fail("Expected trust rejection") } catch (error: HostedSessionException) { assertNull(error.cause) }
    }
    private inner class Fixture {
        var now = 1_900_000_000L
        val rootKeys = keys()
        val phoneKeys = keys()
        val rootId = "dev_" + "1".repeat(32)
        val phoneId = "dev_" + "2".repeat(32)
        val deployment = UUID.randomUUID().toString()
        val root = HostedRoot(deployment, rootId, HostedSession.publicSigning(rootKeys.signingPublic), HostedEnvelope.exportPublic(rootKeys.recipient))
        val rootMember = member(rootId, rootKeys)
        val phoneMember = member(phoneId, phoneKeys)
        val rootState = MemoryHostedTrust()
        val phoneState = MemoryHostedTrust()
        val sender = HostedSession(root, rootId, rootKeys, rootState) { now }
        val phone = HostedSession(root, phoneId, phoneKeys, phoneState) { now }
        fun roster(version: Int, previous: String?, members: List<JsonObject>, expiry: Long = now + 3600): JsonObject {
            val value = buildJsonObject {
                put("deployment_id", deployment); put("version", version); put("previous_hash", previous?.let(::JsonPrimitive) ?: JsonNull)
                put("expires_at", expiry); put("members", JsonArray(members.sortedBy { it.getValue("id").jsonPrimitive.content }))
            }
            val signature = Signature.getInstance("SHA256withECDSA").run {
                initSign(rootKeys.signingPrivate); update("Orion hosted roster v1\u0000".toByteArray(Charsets.US_ASCII) + HostedEnvelope.canonical(value)); sign()
            }
            return buildJsonObject { put("roster", value); put("signature", Base64.getEncoder().encodeToString(signature)) }
        }
        fun hash(entry: JsonObject) = HostedSession.digest(HostedEnvelope.canonical(entry.getValue("roster")))
        val genesis = roster(1, null, listOf(rootMember))
        val approved = roster(2, hash(genesis), listOf(rootMember, phoneMember))
        val chain = JsonArray(listOf(genesis, approved))
        fun approved() { sender.acceptChain(chain); phone.acceptChain(chain) }
        fun event() = sender.encrypt(phoneId, buildJsonObject { put("type", "test.synthetic"); put("text", "synthetic-only-body") })
    }

    @Test fun verifiedChainEncryptAuthenticateAndAtomicCiphertextInbox() {
        val f = Fixture(); f.approved()
        val envelope = f.event()
        assertEquals("synthetic-only-body", f.phone.authenticate(envelope).getValue("text").jsonPrimitive.content)
        assertTrue(f.phone.pendingIncoming().isEmpty())
        assertFalse(f.phone.receiveIntoEncryptedInbox(envelope).duplicate)
        assertTrue(f.phone.receiveIntoEncryptedInbox(envelope).duplicate)
        assertEquals(listOf(envelope), f.phone.pendingIncoming())
        assertFalse(f.phoneState.incoming.values.toString().contains("synthetic-only-body"))
        val restored = HostedSession(f.root, f.phoneId, f.phoneKeys, f.phoneState) { f.now }
        rejected { restored.currentMembers() }
        restored.acceptChain(f.chain)
        assertTrue(restored.receiveIntoEncryptedInbox(envelope).duplicate)
    }

    @Test fun failedCommitAndConflictingEventIdLeaveInboxUnchanged() {
        val f = Fixture(); f.approved(); val envelope = f.event()
        f.phoneState.failCommit = true
        rejected { f.phone.receiveIntoEncryptedInbox(envelope) }
        assertTrue(f.phone.pendingIncoming().isEmpty())
        f.phoneState.failCommit = false
        f.phone.receiveIntoEncryptedInbox(envelope)
        val header = envelope.getValue("header").jsonObject
        val changed = JsonObject(envelope + ("ciphertext" to JsonPrimitive(HostedEnvelope.seal(HostedEnvelope.exportPublic(f.phoneKeys.recipient),
            f.rootKeys.signingPrivate, header, buildJsonObject { put("type", "changed") }))))
        rejected { f.phone.receiveIntoEncryptedInbox(changed) }
        assertEquals(listOf(envelope), f.phone.pendingIncoming())
    }

    @Test fun rollbackForkRevocationAndRemovedIdReadmissionFailClosed() {
        val f = Fixture(); f.approved()
        rejected { f.phone.acceptChain(JsonArray(listOf(f.genesis))) }
        rejected { f.phone.currentMembers() }
        f.phone.acceptChain(f.chain)
        val fork = f.roster(2, f.hash(f.genesis), listOf(f.rootMember, f.phoneMember), f.now + 4000)
        rejected { f.phone.acceptChain(JsonArray(listOf(f.genesis, fork))) }
        val revoked = f.roster(3, f.hash(f.approved), listOf(f.rootMember))
        rejected { f.phone.acceptChain(JsonArray(listOf(f.genesis, f.approved, revoked))) }
        assertEquals(3L, f.phoneState.checkpoint.version)
        rejected { f.phone.acceptChain(f.chain) }
        val readmit = f.roster(4, f.hash(revoked), listOf(f.rootMember, f.phoneMember))
        rejected { f.phone.acceptChain(JsonArray(listOf(f.genesis, f.approved, revoked, readmit))) }
    }

    @Test fun invalidRootKeysMembershipExpiryAndBindingAreRejected() {
        val f = Fixture(); f.approved()
        val wrongRoot = f.root.copy(signingPublic = HostedSession.publicSigning(keys().signingPublic))
        rejected { HostedSession(wrongRoot, f.phoneId, f.phoneKeys, f.phoneState) { f.now } }
        val differentRoot = f.root.copy(encryptionPublic = HostedEnvelope.exportPublic(keys().recipient))
        rejected { HostedSession(differentRoot, f.phoneId, f.phoneKeys, MemoryHostedTrust()) { f.now }.acceptChain(f.chain) }
        val changedMember = member(f.phoneId, keys())
        val changed = f.roster(3, f.hash(f.approved), listOf(f.rootMember, changedMember))
        rejected { f.phone.acceptChain(JsonArray(listOf(f.genesis, f.approved, changed))) }
        f.phone.acceptChain(f.chain)
        f.now += 3601
        rejected { f.phone.currentMembers() }
        rejected { f.phone.acceptChain(f.chain) }
    }

    @Test fun senderHeaderExpiryAndSnapshotsAreBound() {
        val f = Fixture(); f.approved(); val envelope = f.event()
        val detached = f.phone.currentMembers().getValue(f.rootId).toMutableMap()
        detached["encryption_key"] = JsonPrimitive(HostedEnvelope.exportPublic(keys().recipient))
        assertEquals(f.rootMember, f.phone.currentMembers().getValue(f.rootId))
        val header = envelope.getValue("header").jsonObject
        for ((name, value) in listOf("target" to JsonPrimitive(f.rootId), "source" to JsonPrimitive(f.phoneId),
            "roster_hash" to JsonPrimitive("f".repeat(64)), "expires_at" to JsonPrimitive(f.now), "expires_at" to JsonPrimitive(f.now + 301))) {
            rejected { f.phone.authenticate(JsonObject(envelope + ("header" to JsonObject(header + (name to value))))) }
        }
        rejected { f.phone.authenticate(JsonObject(envelope + ("extra" to JsonNull))) }
        f.phone.receiveIntoEncryptedInbox(envelope)
        f.now += 86_500
        assertTrue(f.phone.pendingIncoming().isEmpty())
    }

    @Test fun accountBearerAndDeviceSignaturesNeverMixAndOriginBounds() {
        val f = Fixture(); f.approved(); val requests = mutableListOf<Request>()
        val transport = HostedHttpTransport.forTests("https://hosted.example", f.phone, HostedHttpTransport.Sender { request, _ ->
            requests += request
            when (request.url.encodedPath) {
                "/v1/devices/requests" -> "{\"status\":\"pending\"}"
                "/v1/devices/rosters/page" -> buildJsonObject { put("chain", JsonArray(emptyList())); put("more", false) }.toString()
                else -> "{\"accepted\":true,\"duplicate\":false}"
            }.toByteArray()
        }) { f.now }
        transport.submitEnrollment("synthetic-access-token")
        transport.refreshTrust("synthetic-access-token")
        transport.send(f.rootId, buildJsonObject { put("type", "synthetic") })
        for (request in requests.take(2)) {
            assertEquals("Bearer synthetic-access-token", request.header("Authorization"))
            assertNull(request.header("X-Orion-Signature"))
        }
        val signed = requests.last()
        assertNull(signed.header("Authorization"))
        val raw = Buffer().also { signed.body!!.writeTo(it) }.readByteArray()
        val wire = "POST\n/v1/sealed/events\n${signed.header("X-Orion-Timestamp")}\n${signed.header("X-Orion-Nonce")}\n${HostedSession.digest(raw)}".toByteArray()
        assertTrue(Signature.getInstance("SHA256withECDSA").run {
            initVerify(f.phoneKeys.signingPublic); update(wire); verify(Base64.getDecoder().decode(signed.header("X-Orion-Signature")))
        })
        for (bad in listOf("http://example.com", "https://u:p@example.com", "https://example.com/path", "https://example.com?q=x",
            "https://example.com#x", "https://example.com:0", "https://example.com:65536", "https://example.com\n")) {
            try { HostedHttpTransport.checkedOrigin(bad); fail("Invalid origin") } catch (_: Exception) { }
        }
        f.now += 4000
        val count = requests.size
        rejected { transport.send(f.rootId, buildJsonObject {}) }
        rejected { transport.pollIntoEncryptedInbox() }
        assertEquals(count, requests.size)
    }

    @Test fun remoteAckFollowsCommitAndTimeoutRedeliveryIsIdempotent() {
        val f = Fixture(); f.approved(); val envelope = f.event()
        var acks = 0; var ackFails = false
        val transport = HostedHttpTransport.forTests("https://hosted.example", f.phone, HostedHttpTransport.Sender { request, _ ->
            if (request.method == "DELETE") {
                acks++; assertEquals(1, f.phoneState.incoming.size)
                if (ackFails) error("synthetic timeout")
                "{\"ok\":true}".toByteArray()
            } else buildJsonObject { put("events", JsonArray(listOf(envelope))) }.toString().toByteArray()
        }) { f.now }
        f.phoneState.failCommit = true
        rejected { transport.pollIntoEncryptedInbox() }
        assertEquals(0, acks)
        f.phoneState.failCommit = false; ackFails = true
        rejected { transport.pollIntoEncryptedInbox() }
        assertEquals(1, acks); assertEquals(1, f.phoneState.incoming.size)
        ackFails = false
        assertTrue(transport.pollIntoEncryptedInbox().single().duplicate)
        assertEquals(2, acks); assertEquals(1, f.phoneState.incoming.size)
    }

    @Test fun hostileResponseDuplicateFieldsNestingAndBoundsAreRejected() {
        val f = Fixture(); f.approved()
        for (response in listOf("{\"events\":[],\"events\":[]}", "{\"events\":[],\"\\u0065vents\":[]}",
            "{\"events\":[{\"x\":1,\"x\":2}]}", "[".repeat(1000) + "0" + "]".repeat(1000), "x".repeat(4_000_001))) {
            val transport = HostedHttpTransport.forTests("https://hosted.example", f.phone, HostedHttpTransport.Sender { _, _ -> response.toByteArray() }) { f.now }
            rejected { transport.pollIntoEncryptedInbox() }
        }
    }

    @Test fun pagedRenewalsBeyond129SurviveRestartWithoutIntermediateAuthority() {
        val f = Fixture()
        val history = mutableListOf<JsonObject>()
        repeat(146) { index ->
            history += f.roster(index + 1, history.lastOrNull()?.let(f::hash),
                if (index == 0) listOf(f.rootMember) else listOf(f.rootMember, f.phoneMember),
                if (index == 145) f.now + 3600 else f.now - 1)
        }
        f.phone.acceptPage(JsonArray(history.take(16)), final = false)
        assertEquals(16L, f.phone.pagingCheckpoint().version)
        rejected { f.phone.currentMembers() }
        val restarted = HostedSession(f.root, f.phoneId, f.phoneKeys, f.phoneState) { f.now }
        rejected { restarted.currentMembers() }
        for (page in history.drop(16).chunked(16)) {
            val final = page.last() == history.last()
            restarted.acceptPage(JsonArray(page), final)
            if (!final) rejected { restarted.currentMembers() }
        }
        assertEquals(146L, f.phoneState.checkpoint.version)
        assertEquals(setOf(f.rootId, f.phoneId), restarted.currentMembers().keys)
        rejected { restarted.acceptChain(JsonArray(history.take(128))) }
        assertEquals(146L, f.phoneState.checkpoint.version)
        restarted.acceptPage(JsonArray(emptyList()), final = true)
        assertEquals(2, restarted.currentMembers().size)
    }

    @Test fun pagedHistoryPreservesRetiredIdsAndRejectsGapsForksAndExpiredFinal() {
        val f = Fixture(); f.approved()
        val retiredId = "dev_" + "3".repeat(32)
        val retired = member(retiredId, keys())
        val third = f.roster(3, f.hash(f.approved), listOf(f.rootMember, f.phoneMember, retired))
        val fourth = f.roster(4, f.hash(third), listOf(f.rootMember, f.phoneMember))
        f.phone.acceptPage(JsonArray(listOf(third, fourth)), final = false)
        rejected { f.phone.currentMembers() }
        val restarted = HostedSession(f.root, f.phoneId, f.phoneKeys, f.phoneState) { f.now }
        val readd = f.roster(5, f.hash(fourth), listOf(f.rootMember, f.phoneMember, retired))
        rejected { restarted.acceptPage(JsonArray(listOf(readd)), final = true) }
        assertTrue(retiredId in f.phoneState.usedDeviceIds)
        val gap = f.roster(6, f.hash(fourth), listOf(f.rootMember, f.phoneMember))
        rejected { restarted.acceptPage(JsonArray(listOf(gap)), final = true) }
        val fork = f.roster(5, "f".repeat(64), listOf(f.rootMember, f.phoneMember))
        rejected { restarted.acceptPage(JsonArray(listOf(fork)), final = true) }
        val expired = f.roster(5, f.hash(fourth), listOf(f.rootMember, f.phoneMember), f.now)
        rejected { restarted.acceptPage(JsonArray(listOf(expired)), final = true) }
        assertEquals(5L, f.phoneState.checkpoint.version)
        rejected { restarted.acceptPage(JsonArray(emptyList()), final = true) }
        rejected { restarted.acceptChain(JsonArray(listOf(f.genesis, f.approved, third, fourth))) }
        assertTrue(retiredId in f.phoneState.usedDeviceIds)
    }

    @Test fun pagedRevocationCommitFailureAndCrossSessionRaceFailClosed() {
        val f = Fixture(); f.approved()
        val third = f.roster(3, f.hash(f.approved), listOf(f.rootMember, f.phoneMember))
        f.phoneState.failCommit = true
        rejected { f.phone.acceptPage(JsonArray(listOf(third)), final = true) }
        assertEquals(2L, f.phoneState.checkpoint.version)
        rejected { f.phone.currentMembers() }
        f.phoneState.failCommit = false
        val secondSession = HostedSession(f.root, f.phoneId, f.phoneKeys, f.phoneState) { f.now }
        val competing = f.roster(3, f.hash(f.approved), listOf(f.rootMember, f.phoneMember), f.now + 4000)
        f.phoneState.beforeAdvance = { secondSession.acceptPage(JsonArray(listOf(competing)), final = true) }
        rejected { f.phone.acceptPage(JsonArray(listOf(third)), final = true) }
        assertEquals(f.hash(competing), f.phoneState.checkpoint.digest)
        assertEquals(competing, f.phoneState.signedAnchor)
        val revoked = f.roster(4, f.hash(competing), listOf(f.rootMember))
        rejected { secondSession.acceptPage(JsonArray(listOf(revoked)), final = true) }
        assertEquals(4L, f.phoneState.checkpoint.version)
        rejected { secondSession.currentMembers() }
    }

    @Test fun legacyCheckpointRequiresFullVerifiedMigrationAndPageBoundsAreStrict() {
        val f = Fixture()
        f.phoneState.checkpoint = HostedCheckpoint(2, f.hash(f.approved))
        val third = f.roster(3, f.hash(f.approved), listOf(f.rootMember, f.phoneMember))
        rejected { f.phone.pagingCheckpoint() }
        rejected { f.phone.acceptPage(JsonArray(listOf(third)), final = true) }
        f.phone.acceptChain(f.chain)
        assertEquals(f.approved, f.phoneState.signedAnchor)
        assertEquals(setOf(f.rootId, f.phoneId), f.phoneState.usedDeviceIds)
        rejected { f.phone.acceptPage(JsonArray(emptyList()), final = false) }
        rejected { f.phone.acceptPage(JsonArray(List(17) { third }), final = true) }
        f.phone.acceptPage(JsonArray(listOf(third)), final = true)
        assertEquals(3L, f.phoneState.checkpoint.version)
    }

    @Test fun transportPagesFromVerifiedAnchorAndBoundsUntrustedContinuation() {
        val f = Fixture(); val paths = mutableListOf<String>()
        val transport = HostedHttpTransport.forTests("https://hosted.example", f.phone, HostedHttpTransport.Sender { request, _ ->
            paths += request.url.encodedPath + "?" + request.url.encodedQuery
            val version = request.url.queryParameter("after_version")!!.toLong()
            if (version == 0L) {
                assertNull(request.url.queryParameter("after_hash"))
                buildJsonObject { put("chain", f.chain); put("more", true) }.toString().toByteArray()
            } else {
                assertEquals(f.hash(f.approved), request.url.queryParameter("after_hash"))
                buildJsonObject { put("chain", JsonArray(emptyList())); put("more", false) }.toString().toByteArray()
            }
        }) { f.now }
        rejected { transport.refreshTrust("synthetic", maximumPages = 1) }
        assertEquals(2L, f.phoneState.checkpoint.version)
        rejected { f.phone.currentMembers() }
        transport.refreshTrust("synthetic")
        assertEquals(2, f.phone.currentMembers().size)
        assertTrue(paths.all { "limit=16" in it })
        val malformed = HostedHttpTransport.forTests("https://hosted.example", f.phone, HostedHttpTransport.Sender { _, _ ->
            "{\"chain\":[],\"more\":true}".toByteArray()
        }) { f.now }
        rejected { malformed.refreshTrust("synthetic") }
        rejected { f.phone.currentMembers() }
    }

    @Test fun optionalFullPythonSignedChainInterop() {
        val path = System.getenv("ORION_HPKE_FIXTURE")
        assumeTrue(!path.isNullOrBlank())
        val fixture = Json.parseToJsonElement(Files.readString(Path.of(path!!))).jsonObject
        assumeTrue(fixture.containsKey("signed_chain"))
        fun text(name: String) = fixture.getValue(name).jsonPrimitive.content
        val recipient = TinkProtoKeysetFormat.parseKeyset(Base64.getDecoder().decode(text("python_recipient_private_b64")), InsecureSecretKeyAccess.get(), RegistryConfiguration.get())
        val factory = KeyFactory.getInstance("EC")
        val signing = factory.generatePrivate(PKCS8EncodedKeySpec(Base64.getDecoder().decode(text("signing_private_pkcs8_b64"))))
        val public = factory.generatePublic(X509EncodedKeySpec(Base64.getDecoder().decode(text("signing_public_spki_b64"))))
        val anchor = fixture.getValue("trusted_root").jsonObject
        val rootDevice = anchor.getValue("device").jsonObject
        val root = HostedRoot(anchor.getValue("deployment_id").jsonPrimitive.content, rootDevice.getValue("id").jsonPrimitive.content,
            rootDevice.getValue("signing_key").jsonPrimitive.content, rootDevice.getValue("encryption_key").jsonPrimitive.content)
        val session = HostedSession(root, text("recipient_device_id"), HostedRecipientMaterial(recipient, signing, public), MemoryHostedTrust())
        val chain = fixture.getValue("signed_chain").jsonArray
        for ((index, page) in chain.chunked(16).withIndex()) {
            session.acceptPage(JsonArray(page), final = (index + 1) * 16 >= chain.size)
        }
        val envelope = fixture.getValue("python_session_envelope").jsonObject
        assertEquals(fixture.getValue("payload"), session.authenticate(envelope))
        assertFalse(session.receiveIntoEncryptedInbox(envelope).duplicate)
        assertTrue(session.receiveIntoEncryptedInbox(envelope).duplicate)
        val outputPath = Path.of(text("output_path"))
        // Do not depend on ordering with HostedEnvelopeTest's separate output.
        val output = buildJsonObject {
            put("kotlin_session_envelope", session.encrypt(text("session_sender_device_id"), fixture.getValue("payload").jsonObject))
            put("root_fingerprint", root.fingerprint())
        }
        Files.writeString(Path.of(outputPath.toString() + ".session.json"), output.toString())
    }
}
