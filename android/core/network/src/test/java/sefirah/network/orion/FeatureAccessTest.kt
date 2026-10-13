package sefirah.network.orion

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class FeatureAccessTest {
    @Test fun disablingClipboardWhileOfflineDiscardsPrivateIntentBeforeReenable() {
        val link=LinkProtocol { 100L }
        val enabled=FeatureAccess(clipboard=true)
        val disabled=FeatureAccess(clipboard=false)
        assertTrue(enabled.allowsPublication("clipboard"))
        assertFalse(disabled.allowsPublication("clipboard"))
        link.publish("clipboard",buildJsonObject { put("mime","text/plain") })
        link.publish("file.offer",buildJsonObject {})
        // No socket/outgoing call occurs during this preference change.
        link.discardDenied(disabled::allowsPublication)
        val afterReenable=link.outgoing(true,enabled::allowsPublication).map(::event)
        assertEquals(listOf("file.offer"),afterReenable.map { it.getValue("type").jsonPrimitive.content })
        link.publish("clipboard",buildJsonObject { put("mime","text/plain") })
        assertEquals(listOf("clipboard"),link.outgoing(false,enabled::allowsPublication).map { event(it).getValue("type").jsonPrimitive.content })
    }
    private fun event(wire: String) = Json.parseToJsonElement(wire).jsonObject.getValue("event").jsonObject
    @Test fun revocationDropsPendingProtectedFramesBeforeReconnectRetryAndRetainsIndependentFiles() {
        val link=LinkProtocol { 100L }
        for(type in listOf("sms.thread","sms.messages","sms.remove","call.state","notification.upsert","photos.index","photo.original","file.offer","battery")) {
            assertTrue(link.publish(type,buildJsonObject { put("thread",1) }))
        }
        val original=link.outgoing().associate { event(it).getValue("type").jsonPrimitive.content to event(it).getValue("id").jsonPrimitive.content }
        val revoked=FeatureAccess()
        val retry=link.outgoing(true,revoked::allowsPublication).map(::event)
        assertEquals(setOf("file.offer","battery"),retry.map { it.getValue("type").jsonPrimitive.content }.toSet())
        retry.forEach { assertEquals(original[it.getValue("type").jsonPrimitive.content],it.getValue("id").jsonPrimitive.content) }
        assertFalse(link.knownConversations().any { it.first==1L })
        // Regrant cannot resurrect the removed private frames or their old event IDs.
        val all=FeatureAccess(true,true,true,true,true)
        assertEquals(2,link.outgoing(true,all::allowsPublication).size)
        assertTrue(link.publish("sms.thread",buildJsonObject { put("thread",1) }))
        val fresh=link.outgoing(false,all::allowsPublication).single().let(::event)
        assertNotEquals(original["sms.thread"],fresh.getValue("id").jsonPrimitive.content)
    }
    @Test fun revokingOneFeaturePreservesOtherAcceptedAndPendingState() {
        val link=LinkProtocol { 100L }
        link.publish("sms.thread",buildJsonObject { put("thread",1) },conversationChecksum=8)
        link.outgoing().forEach { link.accepted(event(it).getValue("id").jsonPrimitive.content) }
        link.publish("notification.upsert",buildJsonObject {})
        link.publish("call.state",buildJsonObject {})
        val access=FeatureAccess(sms=true,calls=true,notifications=false)
        assertEquals(listOf("call.state"),link.outgoing(true,access::allowsPublication).map { event(it).getValue("type").jsonPrimitive.content })
        assertEquals(listOf(1L to 8L),link.knownConversations())
        assertEquals(listOf("files","sms","sms-group","calls"),access.capabilities())
    }
    @Test fun callControlRequiresReadStateAndAnswerPermissionIndependently() {
        assertFalse("call-control" in FeatureAccess(callControl=true).capabilities())
        assertFalse("call-control" in FeatureAccess(calls=true).capabilities())
        assertTrue("call-control" in FeatureAccess(calls=true,callControl=true).capabilities())
        assertFalse(FeatureAccess(callControl=true).allowsPublication("call.state"))
    }
    @Test fun photosAndNotificationAccessDisableTheirWholeProductionFamilies() {
        val denied=FeatureAccess()
        for(type in listOf("photos.index","photos.sync","photo.original","notification.upsert","notification.remove","notification.sync","sms.index")) {
            assertFalse(type,denied.allowsPublication(type))
        }
        assertEquals(listOf("files"),denied.capabilities())
        assertTrue(denied.allowsPublication("file.offer")) // User-selected SAF grants remain independent.
        assertTrue(FeatureAccess(photos=true,notifications=true).allowsPublication("photos.index"))
    }
}
