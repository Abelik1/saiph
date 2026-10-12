package sefirah.network.orion

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import sefirah.domain.model.*

class PhoneFeatureFramesTest {
    @Test fun unicodeMessagePagesStayWithinTheExistingLinkFrameLimit() {
        val message=TextMessage(uniqueId=17,addresses=listOf("Synthetic sender"),body="😀".repeat(2048),timestamp=123,messageType=1)
        val frames=PhoneFeatureFrames.encode(MessageList(7,MessageListKind.Open,List(10) { message }))!!
        assertEquals(5,frames.size)
        assertTrue(frames.all { it.second.toString().toByteArray().size<60000 })
        assertEquals("incoming",frames[0].second.getValue("messages").jsonArray[0].jsonObject.getValue("direction").jsonPrimitive.content)
    }
    @Test fun threadCodecPreservesAuthorityAndDoesNotSendAttachments() {
        val frame=PhoneFeatureFrames.encode(ConversationInfo(7,listOf("Synthetic sender"),checksum=123,message=TextMessage(17,listOf("Synthetic sender"),"Synthetic SMS")))!!.single()
        assertEquals("sms.thread",frame.first)
        assertEquals(7L,frame.second.getValue("thread").jsonPrimitive.long)
        assertFalse(frame.second.getValue("message").jsonObject.containsKey("attachments"))
        assertEquals(setOf("thread","recipients","message"),frame.second.keys) // Checksum stays local; Hub schema is unchanged.
    }
    @Test fun endedCallsAndRemovedThreadsReconcileRetainedState() {
        assertEquals("ended",PhoneFeatureFrames.encode(CallInfo(CallState.Ended,""))!!.single().second.getValue("state").jsonPrimitive.content)
        assertEquals("sms.remove",PhoneFeatureFrames.encode(RemoveConversation(7))!!.single().first)
        assertNull(PhoneFeatureFrames.encode(PlaySound(true)))
    }
}
