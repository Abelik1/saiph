package sefirah.network.orion

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import java.util.UUID

class LinkProtocolTest {
    private fun thread(id: Long, version: Int = 1) = buildJsonObject {
        put("thread", id); put("message", buildJsonObject { put("id", version); put("body", "synthetic") })
    }
    private fun publication(wire: String) = Json.parseToJsonElement(wire).jsonObject.getValue("event").jsonObject
    private fun acknowledge(link: LinkProtocol, wire: String) = link.accepted(publication(wire).getValue("id").jsonPrimitive.content)
    @Test fun trustedHostnameAndIpQrsUseFixedMeshIpWithoutDns() {
        val legacyHosts = listOf("http://legacy.example.invalid:8765", "http://legacy.example.invalid:8765/")
        if (MeshOrigin.DEFAULT.isEmpty()) legacyHosts.forEach { assertTrue(runCatching { MeshOrigin.validate(it) }.isFailure) }
        else legacyHosts.forEach { assertEquals(MeshOrigin.DEFAULT, MeshOrigin.validate(it)) }
        listOf("http://100.64.0.2:8765", "http://100.64.0.2:8765/").forEach {
            assertEquals("http://100.64.0.2:8765", MeshOrigin.validate(it))
        }
        assertEquals("http://100.64.0.2:8765" to "12345678",
            MeshOrigin.pairing("orion://pair?v=1&hub=http%3A%2F%2F100.64.0.2%3A8765&code=12345678"))
    }
    @Test fun rejectsQrThatWouldLeakPairingKeysOffMesh() {
        val code = "12345678"
        val good = "orion://pair?v=1&hub=http%3A%2F%2Flegacy.example.invalid%3A8765&code=$code"
        if (MeshOrigin.DEFAULT.isEmpty()) assertTrue(runCatching { MeshOrigin.pairing(good) }.isFailure)
        else assertEquals(MeshOrigin.DEFAULT to code, MeshOrigin.pairing(good))
        listOf(good.replace("legacy.example.invalid", "attacker.example"), good + "&code=87654321",
            good.replace("v=1", "v=2"), good.replace(code, "1234"), good + "#fragment").forEach {
            assertTrue(runCatching { MeshOrigin.pairing(it) }.isFailure)
        }
        listOf("http://legacy.example.invalid:8765@attacker.example:8765", "http://legacy.example.invalid:8765/v1",
            "http://legacy.example.invalid:8765?foo=bar", "https://legacy.example.invalid:8765").forEach {
            assertTrue(runCatching { MeshOrigin.validate(it) }.isFailure)
        }
    }
    @Test fun retriesRetainIdsUntilAcceptedAndDoNotOutliveTtl() {
        var now = 100L; val link = LinkProtocol { now }
        assertTrue(link.publish("battery", buildJsonObject { put("battery_level", 80) }))
        val first = link.outgoing().single()
        assertEquals(first, link.outgoing().single())
        val id = Json.parseToJsonElement(first).jsonObject.getValue("event").jsonObject.getValue("id").jsonPrimitive.content
        link.accepted(id); assertTrue(link.outgoing().isEmpty())
        link.publish("battery", buildJsonObject {}); now += 60; assertTrue(link.outgoing().isEmpty())
    }
    @Test fun deduplicatesDeliveriesAndAcksExpiredEventsWithoutExecutingThem() {
        var now = 100L; val link = LinkProtocol { now }; var calls = 0
        val event = buildJsonObject { put("id", UUID.randomUUID().toString()); put("expires_at", 120.125) }
        val ack = link.receive(event) { calls++ }
        assertEquals(ack, link.receive(event) { calls++ }); assertEquals(1, calls)
        now = 121
        link.receive(buildJsonObject { put("id", UUID.randomUUID().toString()); put("expires_at", 120) }) { calls++ }
        assertEquals(1, calls)
    }
    @Test fun handlerFailureDoesNotLoseAnEventAndQueueIsBounded() {
        val link = LinkProtocol { 100 }
        val event = buildJsonObject { put("id", UUID.randomUUID().toString()); put("expires_at", 120) }
        assertTrue(runCatching { link.receive(event) { error("handler unavailable") } }.isFailure)
        var calls = 0; link.receive(event) { calls++ }; assertEquals(1, calls)
        repeat(512) { assertTrue(link.publish("battery", buildJsonObject {})) }
        assertFalse(link.publish("battery", buildJsonObject {}))
    }
    @Test fun initialConversationBurstSendsEachEventOnceAndRetriesKeepIds() {
        val link = LinkProtocol { 100 }
        val sent = mutableListOf<String>()
        repeat(200) {
            assertTrue(link.publish("sms.thread", buildJsonObject { put("thread", it) }))
            sent += link.outgoing(retry = false)
        }
        assertEquals(200, sent.size)
        assertTrue(link.outgoing(retry = false).isEmpty())
        assertEquals(sent, link.outgoing(retry = true)) // Heartbeat/reconnect retains original IDs.
        val accepted = Json.parseToJsonElement(sent.first()).jsonObject.getValue("event").jsonObject.getValue("id").jsonPrimitive.content
        link.accepted(accepted)
        assertEquals(sent.drop(1), link.outgoing(retry = true))
    }
    @Test fun fiveHundredUnchangedConversationsAcrossTwentyReconnectsMintOnlyFiveHundredIds() {
        val link = LinkProtocol { 100 }; link.identity("paired-phone")
        repeat(500) { assertTrue(link.publish("sms.thread", thread(it.toLong()), conversationChecksum = it.toLong()+1)) }
        val initial = link.outgoing();assertEquals(500, initial.size)
        // Welcome while ACKs are still in flight must reuse the original queue.
        repeat(20) {
            repeat(500) { assertTrue(link.publish("sms.thread", thread(it.toLong()), conversationChecksum = it.toLong()+1)) }
            assertEquals(initial, link.outgoing())
        }
        initial.forEach { acknowledge(link,it) }
        repeat(20) {
            assertEquals(500, link.knownConversations().size)
            repeat(500) { assertTrue(link.publish("sms.thread", thread(it.toLong()), conversationChecksum = it.toLong()+1)) }
            assertTrue(link.outgoing().isEmpty())
        }
        assertEquals((0L..499L).associateWith { it+1 },link.knownConversations().toMap())
    }
    @Test fun changedNewAndDeletedThreadsPublishAndTargetsAreIndependent() {
        val link=LinkProtocol { 100 }
        link.publish("sms.thread",thread(1),conversationChecksum=11);acknowledge(link,link.outgoing().single())
        link.publish("sms.thread",thread(1,2),conversationChecksum=12)
        link.publish("sms.thread",thread(2),conversationChecksum=21)
        val changed=link.outgoing();assertEquals(2,changed.size)
        assertEquals(11L,link.knownConversations().toMap()[1L]) // Changes are not known before ACK.
        changed.forEach { acknowledge(link,it) }
        assertEquals(mapOf(1L to 12L,2L to 21L),link.knownConversations().toMap())
        // A thread absent from the provider is still in knownThreads, so the
        // retained upstream sendConversations emits its removal on reconnect.
        link.publish("sms.remove",buildJsonObject { put("thread",1) })
        val removal=link.outgoing().single();assertEquals("sms.remove",publication(removal).getValue("type").jsonPrimitive.content)
        acknowledge(link,removal)
        assertFalse(link.knownConversations().toMap().containsKey(1L)) // Upstream will not regenerate the removal on every reconnect.
        link.publish("sms.remove",buildJsonObject { put("thread",1) });assertTrue(link.outgoing().isEmpty())
        link.publish("sms.thread",thread(1,3),conversationChecksum=13) // A provider reusing a deleted ID is still new state.
        val readded=link.outgoing().single();acknowledge(link,readded)
        assertEquals(13L,link.knownConversations().toMap()[1L])
        link.publish("sms.thread",thread(2),listOf("new-desktop"),21)
        assertEquals(listOf("new-desktop"),publication(link.outgoing().single()).getValue("targets").jsonArray.map { it.jsonPrimitive.content })
    }
    @Test fun unacceptedExpiredAndCapacityRejectedUpdatesRemainRetryable() {
        var now=100L;val link=LinkProtocol { now }
        link.publish("sms.thread",thread(1),conversationChecksum=11);val first=link.outgoing().single()
        assertEquals(Long.MIN_VALUE,link.knownConversations().toMap()[1L])
        now+=60;assertTrue(link.outgoing().isEmpty());acknowledge(link,first) // Late ACK cannot bless an expired event.
        assertEquals(Long.MIN_VALUE,link.knownConversations().toMap()[1L])
        link.publish("sms.thread",thread(1),conversationChecksum=11)
        val second=link.outgoing().single();assertNotEquals(first,second)
        repeat(511) { link.publish("battery",buildJsonObject {}) }
        assertTrue(link.publish("sms.thread",thread(1),conversationChecksum=11)) // Same pending ID is reusable at capacity.
        assertFalse(link.publish("sms.thread",thread(2),conversationChecksum=21))
        acknowledge(link,second)
        assertTrue(link.publish("sms.thread",thread(2),conversationChecksum=21))
    }
    @Test fun olderAcknowledgementCannotHideNewerPendingUpdate() {
        val link=LinkProtocol { 100 }
        link.publish("sms.thread",thread(1),conversationChecksum=11);val old=link.outgoing().single()
        link.publish("sms.thread",thread(1,2),conversationChecksum=12);val newer=link.outgoing().last()
        acknowledge(link,newer);acknowledge(link,old)
        assertEquals(12L,link.knownConversations().toMap()[1L])
        link.publish("sms.thread",thread(1,2),conversationChecksum=12);assertTrue(link.outgoing().isEmpty())
        link.publish("sms.thread",thread(1,1),conversationChecksum=11);assertEquals(1,link.outgoing().size)
    }
    @Test fun permissionRegrantPairRepairAndProcessRestartRefreshWithoutDroppingPendingIds() {
        val link=LinkProtocol { 100 };link.identity("original-pair")
        link.publish("sms.thread",thread(1),conversationChecksum=11);acknowledge(link,link.outgoing().single())
        link.publish("sms.thread",thread(2),conversationChecksum=21);val pending=link.outgoing().single()
        link.invalidateConversations()
        assertTrue(link.knownConversations().all { it.second==Long.MIN_VALUE })
        link.publish("sms.thread",thread(2),conversationChecksum=21);assertEquals(pending,link.outgoing().single())
        link.publish("sms.thread",thread(1),conversationChecksum=11);assertEquals(2,link.outgoing().size)
        link.identity("repaired-pair");assertTrue(link.knownConversations().isEmpty());assertTrue(link.outgoing().isEmpty())
        link.publish("sms.thread",thread(1),conversationChecksum=11);assertEquals(1,link.outgoing().size)
        val restarted=LinkProtocol { 100 };assertTrue(restarted.knownConversations().isEmpty())
        restarted.publish("sms.thread",thread(1),conversationChecksum=11);assertEquals(1,restarted.outgoing().size)
    }
    @Test fun conversationKnowledgeIsBoundedAndEvictionOnlyCausesSafeRepublishing() {
        val link=LinkProtocol { 100 }
        repeat(1100) {
            link.publish("sms.thread",thread(it.toLong()),conversationChecksum=it.toLong()+1)
            acknowledge(link,link.outgoing().single())
        }
        assertEquals(1024,link.knownConversations().size)
        link.publish("sms.thread",thread(0),conversationChecksum=1);assertEquals(1,link.outgoing().size)
    }
    @Test fun pairingRepairDiscardsBufferedOldSessionEventsWithoutExecutingOrAcknowledgingThem() {
        val link=LinkProtocol { 100 };link.identity("old-pair");var calls=0
        val buffered=buildJsonObject { put("id",UUID.randomUUID().toString());put("expires_at",150) }
        link.identity("new-pair")
        assertNull(link.receiveForIdentity("old-pair",buffered) { calls++ })
        assertEquals(0,calls)
        val current=buildJsonObject { put("id",UUID.randomUUID().toString());put("expires_at",150) }
        assertNotNull(link.receiveForIdentity("new-pair",current) { calls++ })
        assertEquals(1,calls)
    }
}
