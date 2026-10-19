// SPDX-License-Identifier: GPL-3.0-only
package sefirah.network.orion

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import sefirah.domain.model.*

/**
 * Saiph Cloud features a Hub phone already had: notification buttons and replies,
 * MMS pictures and group replies. Synthetic data only; the same literals are
 * checked by the desktop in tests/test_hosted_phone.py.
 */
class HostedParityFramesTest {
    companion object {
        const val KEY = "0|com.synthetic.chat|1|null|10001"
        const val FEATURES_WIRE = """{"features":["notification-actions","sms-mms","sms-group"],"type":"phone.features"}"""
        const val ACTIONS_WIRE = """{"actions":[{"index":0,"label":"Mark as read"}],"key":"0|com.synthetic.chat|1|null|10001","reply_key":"synthetic_reply","timestamp":1760000000000,"type":"notification.actions"}"""
        const val ACTION_WIRE = """{"index":0,"key":"0|com.synthetic.chat|1|null|10001","type":"notification.action"}"""
        const val REPLY_WIRE = """{"key":"0|com.synthetic.chat|1|null|10001","reply_key":"synthetic_reply","text":"On my way","type":"notification.reply"}"""
        const val OPEN_WIRE = """{"key":"0|com.synthetic.chat|1|null|10001","type":"notification.open"}"""
        const val PARTS_WIRE = """{"message":41,"parts":[{"mime":"image/jpeg","name":"synthetic.jpg","part":3}],"thread":7,"type":"sms.attachments"}"""
        const val REQUEST_WIRE = """{"message":41,"part":3,"thread":7,"type":"sms.attachment.request"}"""
    }
    private fun json(value: String) = Json.parseToJsonElement(value).jsonObject
    private fun wire(value: JsonObject) = String(HostedEnvelope.canonical(value), Charsets.UTF_8)
    private val everything = FeatureAccess(sms = true, notifications = true)

    @Test fun featuresFollowNotificationAccessAndTheTextsSwitch() {
        assertEquals(FEATURES_WIRE, wire(HostedPhoneFrames.featuresPayload(HostedPhoneFrames.features(everything, true))))
        assertEquals(listOf("notification-actions"), HostedPhoneFrames.features(everything, false))
        assertEquals(listOf("sms-mms", "sms-group"), HostedPhoneFrames.features(FeatureAccess(sms = true), true))
        assertEquals(emptyList<String>(), HostedPhoneFrames.features(FeatureAccess(), true))
        // Never in phone.capabilities: older desktops refuse names they do not know there.
        assertFalse(HostedPhoneFrames.capabilities(everything, true).any { it in HostedPhoneFrames.features(everything, true) })
    }

    @Test fun notificationActionsWireContractMatchesTheDesktop() {
        assertEquals(ACTIONS_WIRE, wire(HostedNotificationFrames.actions(KEY, 1_760_000_000_000, listOf(0 to "Mark as read"), "synthetic_reply")!!))
        assertEquals(HostedNotificationCommand.Action(KEY, 0), HostedNotificationFrames.command(json(ACTION_WIRE)))
        assertEquals(HostedNotificationCommand.Reply(KEY, "synthetic_reply", "On my way"), HostedNotificationFrames.command(json(REPLY_WIRE)))
        assertEquals(HostedNotificationCommand.Open(KEY), HostedNotificationFrames.command(json(OPEN_WIRE)))
    }

    @Test fun notificationActionsAreBoundedAndOmittedWhenThereAreNone() {
        assertNull(HostedNotificationFrames.actions(KEY, 1, emptyList(), null))
        assertNull(HostedNotificationFrames.actions(KEY, 1, emptyList(), "bad\nkey"))
        assertNull(HostedNotificationFrames.actions("key with spaces", 1, listOf(0 to "A"), null))
        val many = HostedNotificationFrames.actions(KEY, -5, List(14) { it to "x".repeat(200) } + (0 to "Duplicate") + (100 to "Too high"), "")!!
        assertEquals(10, many.getValue("actions").jsonArray.size)
        assertEquals(0L, many.getValue("timestamp").jsonPrimitive.long)
        assertEquals("", many.getValue("reply_key").jsonPrimitive.content)
        assertTrue(many.getValue("actions").jsonArray.all { it.jsonObject.getValue("label").jsonPrimitive.content.length == 120 })
        val replyOnly = HostedNotificationFrames.actions(KEY, 1, listOf(0 to null), "r")!!
        assertEquals("", replyOnly.getValue("actions").jsonArray.single().jsonObject.getValue("label").jsonPrimitive.content)
    }

    @Test fun notificationCommandsRefuseOtherShapes() {
        for (bad in listOf(
            """{"index":0,"key":"$KEY","type":"notification.action","extra":1}""",
            """{"index":"0","key":"$KEY","type":"notification.action"}""",
            """{"index":100,"key":"$KEY","type":"notification.action"}""",
            """{"index":-1,"key":"$KEY","type":"notification.action"}""",
            """{"key":"$KEY","reply_key":"","text":"Hi","type":"notification.reply"}""",
            """{"key":"$KEY","reply_key":"r","text":"   ","type":"notification.reply"}""",
            """{"key":"$KEY","reply_key":"r","text":"${"x".repeat(4097)}","type":"notification.reply"}""",
            """{"key":"bad key","type":"notification.open"}""",
            """{"key":"$KEY","type":"notification.dismiss"}""",
        )) assertNull(bad, HostedNotificationFrames.command(json(bad)))
        // 4096 characters even when each is an emoji (two UTF-16 units), as the desktop counts them.
        assertNotNull(HostedNotificationFrames.command(json("""{"key":"$KEY","reply_key":"r","text":"${"😀".repeat(4096)}","type":"notification.reply"}""")))
    }

    @Test fun mmsPartsWireContractMatchesTheDesktop() {
        val message = TextMessage(41, listOf("+15550100"), "", 1, messageType = 1, subscriptionId = 1,
            attachments = listOf(SmsAttachment("synthetic.jpg", "image/jpeg", partId = 3), SmsAttachment("text", "text/plain", partId = 4),
                SmsAttachment("smil", "application/smil", partId = 5)))
        assertEquals(PARTS_WIRE, wire(HostedPhoneFrames.attachments(7, message)!!))
        assertNull(HostedPhoneFrames.attachments(7, message.copy(attachments = null)))
        assertEquals(HostedPhoneCommand.SmsPart(7, 41, 3), HostedPhoneFrames.command(json(REQUEST_WIRE)))
        assertNull(HostedPhoneFrames.command(json("""{"message":41,"part":-1,"thread":7,"type":"sms.attachment.request"}""")))
        assertNull(HostedPhoneFrames.command(json("""{"message":41,"thread":7,"type":"sms.attachment.request"}""")))
        assertTrue(HostedPhoneFrames.isEffect(HostedPhoneCommand.SmsPart(7, 41, 3)))  // One upload per request.
        assertTrue(HostedPhoneFrames.mayPublish("sms.attachments", FeatureAccess(sms = true), true))
        assertFalse(HostedPhoneFrames.mayPublish("sms.attachments", FeatureAccess(sms = true), false))
    }

    @Test fun mmsPartAnswerWrapsTheManifestForTheRequest() {
        val request = "6f1c1b6e-34b8-4a8b-9f0c-6f1f7d0b2a11"
        val wrapped = HostedPhoneFrames.smsAttachmentOriginal(7, 41, 3, request)(buildJsonObject { put("type", "file.encrypted") })
        assertEquals("""{"file":{"type":"file.encrypted"},"message":41,"part":3,"request":"$request","thread":7,"type":"sms.attachment.original"}""", wire(wrapped))
        assertThrows(IllegalArgumentException::class.java) { HostedPhoneFrames.smsAttachmentOriginal(7, 41, 3, "not-a-request") }
        assertEquals("synthetic_photo_.jpg", MmsParts.safeName("synthetic/photo?.jpg", 3))
        assertEquals("attachment_3", MmsParts.safeName("..", 3))
        assertEquals("image/jpeg", MmsParts.safeMime("Image/JPEG; name=x"))
        assertEquals("application/octet-stream", MmsParts.safeMime("not a type"))
    }
}
