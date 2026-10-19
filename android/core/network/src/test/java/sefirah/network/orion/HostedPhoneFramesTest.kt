// SPDX-License-Identifier: GPL-3.0-only
package sefirah.network.orion

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import sefirah.domain.model.*

/** Synthetic numbers and texts only. Mirrors the desktop's tests/test_hosted_phone.py shapes. */
class HostedPhoneFramesTest {
    @Test fun galleryNeedsSeparateOptInPermissionAndSubscription() {
        val access = FeatureAccess(photos = true)
        assertFalse("photos" in HostedPhoneFrames.capabilities(access, false))
        assertFalse("photos" in HostedPhoneFrames.capabilities(FeatureAccess(), false, true))
        assertTrue("photos" in HostedPhoneFrames.capabilities(access, false, true))
        assertTrue(HostedPhoneFrames.allowed("photo.request", "desk", setOf("desk"), access, false, true))
        assertFalse(HostedPhoneFrames.allowed("photo.request", "stranger", setOf("desk"), access, false, true))
        assertFalse(HostedPhoneFrames.allowed("photo.request", "desk", setOf("desk"), access, true, false))
        assertFalse(HostedPhoneFrames.mayPublish("photos.item", access, true, false))
        assertTrue(HostedPhoneFrames.mayPublish("photos.item", access, false, true))
        assertEquals(HostedPhoneCommand.PhotoRequest("41"), parse("""{"type":"photo.request","id":"41"}"""))
        for (value in listOf("../private", "0", "-1", "9007199254740992"))
            assertNull(parse("""{"type":"photo.request","id":"$value"}"""))
        assertNull(parse("""{"type":"photo.request","id":"41","path":"private"}"""))
    }
    companion object {
        const val THREAD_WIRE = """{"message":{"addresses":["+15550100"],"body":"Synthetic hello","direction":"incoming","id":41,"subscription":1,"timestamp":1760000000000},"recipients":["+15550100"],"thread":7,"type":"sms.thread"}"""
        const val SEND_WIRE = """{"text":"On my way 😀","thread":7,"type":"sms.send"}"""
        const val SUBSCRIBE_WIRE = """{"label":"Synthetic desk","type":"phone.subscribe"}"""
        const val HANDLED_WIRE = """{"by":"Synthetic laptop","operation":"answer","type":"call.handled"}"""
        const val REFUSED_WIRE = """{"by":"Synthetic laptop","handled":"answer","reason":"handled","request":"reject","type":"call.refused"}"""
        const val BUSY_WIRE = """{"by":"","handled":"","reason":"in_call","request":"dial","type":"call.refused"}"""
    }
    private val everything = FeatureAccess(sms = true, calls = true, callControl = true, contacts = true, callLog = true, callDial = true)
    private val root = "dev_root"

    @Test fun capabilitiesNeedTheOwnersSwitchAndEachPermission() {
        assertEquals(listOf("files"), HostedPhoneFrames.capabilities(everything, textsAndCalls = false))
        assertEquals(listOf("files", "sms", "calls", "call-control", "call-dial", "contacts", "call-log"),
            HostedPhoneFrames.capabilities(everything, textsAndCalls = true))
        // Answering needs both phone state and call control.
        assertEquals(listOf("files"), HostedPhoneFrames.capabilities(FeatureAccess(callControl = true), true))
        assertEquals(listOf("files", "calls"), HostedPhoneFrames.capabilities(FeatureAccess(calls = true), true))
        assertTrue(HostedPhoneFrames.mayPublish("phone.capabilities", FeatureAccess(), false))
        assertFalse(HostedPhoneFrames.mayPublish("sms.thread", everything, false))
        assertFalse(HostedPhoneFrames.mayPublish("contacts.results", FeatureAccess(sms = true), true))
        assertFalse(HostedPhoneFrames.mayPublish("clipboard.text", everything, true))
    }

    @Test fun anySubscribedComputerMayCauseAPhoneActionButOnlyWhenAllowed() {
        val computers = setOf(root, "dev_laptop")
        assertTrue(HostedPhoneFrames.allowed("sms.send", root, computers, everything, true))
        assertTrue(HostedPhoneFrames.allowed("call.command", "dev_laptop", computers, everything, true)) // Not only the root.
        assertFalse(HostedPhoneFrames.allowed("sms.send", "dev_unsubscribed", computers, everything, true))
        assertFalse(HostedPhoneFrames.allowed("sms.send", root, emptySet(), everything, true))
        assertFalse(HostedPhoneFrames.allowed("sms.send", root, computers, everything, false))
        assertFalse(HostedPhoneFrames.allowed("sms.send", root, computers, FeatureAccess(calls = true), true))
        assertFalse(HostedPhoneFrames.allowed("call.command", root, computers, FeatureAccess(calls = true), true))
        assertTrue(HostedPhoneFrames.allowed("call.command", root, computers, FeatureAccess(calls = true, callControl = true), true))
        assertFalse(HostedPhoneFrames.allowed("call.dial", root, computers, FeatureAccess(calls = true, callControl = true), true))
        assertFalse(HostedPhoneFrames.allowed("phone.ring", root, computers, everything, true))
        // MMS parts follow the texts switch and SMS permission ("sms-mms" in phone.features).
        assertTrue(HostedPhoneFrames.allowed("sms.attachment.request", root, computers, everything, true))
        assertFalse(HostedPhoneFrames.allowed("sms.attachment.request", root, computers, everything, false))
        assertTrue(HostedPhoneFrames.mayPublish("call.refused", FeatureAccess(callDial = true), true))
        assertFalse(HostedPhoneFrames.mayPublish("call.refused", everything, false))
        assertFalse(HostedPhoneFrames.mayPublish("call.handled", FeatureAccess(callControl = true), true))
    }

    @Test fun subscriptionsNameAComputerInOneShortLine() {
        fun subscribe(json: String) = HostedPhoneFrames.subscribe(Json.parseToJsonElement(json).jsonObject)
        assertEquals("Synthetic desk", subscribe(SUBSCRIBE_WIRE))
        listOf("""{"type":"phone.subscribe","label":""}""", """{"type":"phone.subscribe","label":"  "}""",
            """{"type":"phone.subscribe","label":"Desk\nPC"}""", """{"type":"phone.subscribe","label":"${"x".repeat(41)}"}""",
            """{"type":"phone.subscribe","label":7}""", """{"type":"phone.subscribe","label":"Desk","root":true}""",
            """{"type":"sms.sync","label":"Desk"}""").forEach { assertNull(it, subscribe(it)) }
    }

    @Test fun theFirstAnswerOrDeclineWinsAndLaterOnesAreToldWho() {
        var now = 1_000L
        val race = HostedCallRace { now }
        val ringing = Any()
        assertEquals(HostedCallRace.Refused("not_ringing"), race.claimCall("Synthetic desk", true, phoneRinging = true))
        race.observe(ringing, CallState.Ringing)
        race.observe(ringing, CallState.Ringing) // The same event copied for two computers counts once.
        assertEquals(HostedCallRace.Refused("not_ringing"), race.claimCall("Synthetic desk", true, phoneRinging = false))
        assertEquals(HostedCallRace.Won, race.claimCall("Synthetic laptop", false, phoneRinging = true))
        assertEquals(HostedCallRace.Refused("handled", "reject", "Synthetic laptop"), race.claimCall("Synthetic desk", true, phoneRinging = true))
        assertEquals(HostedCallRace.Refused("handled", "reject", "Synthetic laptop"), race.claimCall("Synthetic desk", false, phoneRinging = true))
        // Declining ends the call; Android then reports it as missed, which computers must not alert on.
        now += 2_000
        assertEquals(CallState.Ended, race.published(CallState.MissedCall))
        race.observe(Any(), CallState.Ended)
        now += 20_000
        assertEquals(CallState.MissedCall, race.published(CallState.MissedCall))
        // A new call starts a new race.
        race.observe(Any(), CallState.Ringing)
        assertEquals(HostedCallRace.Won, race.claimCall("Synthetic desk", true, phoneRinging = true))
        assertEquals(HostedCallRace.Refused("handled", "answer", "Synthetic desk"), race.claimCall("Synthetic laptop", false, phoneRinging = false))
        assertEquals(CallState.MissedCall, race.published(CallState.MissedCall)) // Answered, so not a remote decline.
    }

    @Test fun aDialIsRefusedWhileThePhoneIsOnACallOrAlreadyPlacingOne() {
        var now = 0L
        val race = HostedCallRace { now }
        assertEquals(HostedCallRace.Refused("in_call"), race.claimDial(phoneBusy = true))
        assertEquals(HostedCallRace.Won, race.claimDial(phoneBusy = false))
        assertEquals(HostedCallRace.Refused("dialing"), race.claimDial(phoneBusy = false))
        now += 11_000
        assertEquals(HostedCallRace.Won, race.claimDial(phoneBusy = false))
        race.observe(Any(), CallState.Ended) // A finished call frees the phone at once.
        assertEquals(HostedCallRace.Won, race.claimDial(phoneBusy = false))
    }

    @Test fun raceResultsMatchTheDesktopWire() {
        assertEquals(HANDLED_WIRE, String(HostedEnvelope.canonical(HostedPhoneFrames.callHandled(true, "Synthetic laptop")), Charsets.US_ASCII))
        assertEquals(REFUSED_WIRE, String(HostedEnvelope.canonical(HostedPhoneFrames.callRefused("reject",
            HostedCallRace.Refused("handled", "answer", "Synthetic laptop"))), Charsets.US_ASCII))
        assertEquals(BUSY_WIRE, String(HostedEnvelope.canonical(HostedPhoneFrames.callRefused("dial", HostedCallRace.Refused("in_call"))), Charsets.US_ASCII))
    }

    private fun parse(json: String) = HostedPhoneFrames.command(Json.parseToJsonElement(json).jsonObject)

    @Test fun commandsHaveExactShapes() {
        assertEquals(HostedPhoneCommand.SmsSync, parse("""{"type":"sms.sync"}"""))
        assertEquals(HostedPhoneCommand.CallsLog, parse("""{"type":"calls.log.request"}"""))
        assertEquals(HostedPhoneCommand.SmsOpen(7), parse("""{"type":"sms.open","thread":7}"""))
        assertEquals(HostedPhoneCommand.SmsSend(7, "On my way"), parse("""{"type":"sms.send","thread":7,"text":"On my way"}"""))
        assertEquals(HostedPhoneCommand.SmsCompose("+15550100", "Hi"), parse("""{"type":"sms.compose","addresses":["+15550100"],"text":"Hi"}"""))
        assertEquals(HostedPhoneCommand.Call(true), parse("""{"type":"call.command","operation":"answer"}"""))
        assertEquals(HostedPhoneCommand.Call(false), parse("""{"type":"call.command","operation":"reject"}"""))
        assertEquals(HostedPhoneCommand.Dial("+1 (555) 010-0"), parse("""{"type":"call.dial","number":"+1 (555) 010-0"}"""))
        assertEquals(HostedPhoneCommand.ContactsSearch("Syn"), parse("""{"type":"contacts.search","query":"Syn"}"""))
        // Only outside effects consume an at-most-once receipt.
        assertTrue(listOf(HostedPhoneCommand.SmsSend(7, "x"), HostedPhoneCommand.SmsCompose("+15550100", "x"), HostedPhoneCommand.Call(true),
            HostedPhoneCommand.Dial("+15550100")).all(HostedPhoneFrames::isEffect))
        assertFalse(listOf(HostedPhoneCommand.SmsSync, HostedPhoneCommand.SmsOpen(7), HostedPhoneCommand.ContactsSearch("Syn"),
            HostedPhoneCommand.CallsLog).any(HostedPhoneFrames::isEffect))
    }

    @Test fun malformedOrUnsafeCommandsAreIgnored() {
        listOf(
            """{"type":"sms.sync","all":true}""",
            """{"type":"sms.open","thread":"7"}""",
            """{"type":"sms.open","thread":-7}""",
            """{"type":"sms.open","thread":7.5}""",
            """{"type":"sms.send","thread":7,"text":"   "}""",
            """{"type":"sms.send","thread":7,"text":"${"x".repeat(4097)}"}""",
            """{"type":"sms.send","thread":7,"text":"\ud800"}""",
            """{"type":"sms.send","thread":7,"text":"Hi","recipients":["+15550100"]}""",
            """{"type":"sms.compose","addresses":["+15550100","+15550101"],"text":"Group"}""",
            """{"type":"sms.compose","addresses":["+1555\n0100"],"text":"Hi"}""",
            """{"type":"sms.compose","addresses":[7],"text":"Hi"}""",
            """{"type":"call.command","operation":"hold"}""",
            """{"type":"call.dial","number":"*21*5550100#"}""",
            """{"type":"call.dial","number":"+()"}""",
            """{"type":"contacts.search","query":""}""",
            """{"type":"contacts.search","query":"${"x".repeat(65)}"}""",
            """{"type":"phone.ring"}""",
            """{"type":"sms.thread","thread":7}""",
            """{"thread":7}""",
        ).forEach { assertNull(it, parse(it)) }
        // Emoji count once each, as on the computer: 4096 of them are allowed by shape.
        assertNotNull(parse("""{"type":"sms.send","thread":7,"text":"${"😀".repeat(4096)}"}"""))
    }

    @Test fun cleanNeverSplitsASurrogatePairAndReplacesLoneHalves() {
        assertEquals("ab", HostedPhoneFrames.clean("ab😀", 3))
        assertEquals("ab😀", HostedPhoneFrames.clean("ab😀", 4))
        assertEquals("a�b", HostedPhoneFrames.clean("a\uD800b", 10))
        HostedEnvelope.canonical(JsonPrimitive(HostedPhoneFrames.clean("x\uDC00😀".repeat(100), 151)))
    }

    private fun keys(value: JsonObject) = value.keys

    @Test fun textsBecomeExactPayloadsThatFitOneSealedEvent() {
        val message = TextMessage(uniqueId = 41, addresses = listOf("+15550100", ""), body = "😀".repeat(2048), timestamp = 123,
            messageType = 1, subscriptionId = -1, attachments = listOf(SmsAttachment("photo.jpg", "image/jpeg", partId = 3)))
        val (thread, parts) = HostedPhoneFrames.encode(ConversationInfo(7, listOf("+15550100"), checksum = 99, message = message))!!
        assertEquals("""{"message":41,"parts":[{"mime":"image/jpeg","name":"photo.jpg","part":3}],"thread":7,"type":"sms.attachments"}""",
            String(HostedEnvelope.canonical(parts), Charsets.UTF_8))
        assertEquals(setOf("type", "thread", "recipients", "message"), keys(thread))
        assertEquals(setOf("id", "addresses", "body", "timestamp", "direction", "subscription"), keys(thread.getValue("message").jsonObject))
        assertEquals(listOf("+15550100"), thread.getValue("message").jsonObject.getValue("addresses").jsonArray.map { it.jsonPrimitive.content })
        assertTrue(HostedPhoneFrames.fits(thread))
        val pages = HostedPhoneFrames.encode(MessageList(7, MessageListKind.Open, List(12) { message.copy(uniqueId = it.toLong()) }))!!
        assertEquals(20, pages.size)  // Ten messages, then each one's MMS parts.
        assertTrue(pages.take(10).all { HostedPhoneFrames.fits(it) && it.getValue("messages").jsonArray.size == 1 && it.getValue("type").jsonPrimitive.content == "sms.messages" })
        assertTrue(pages.drop(10).all { it.getValue("type").jsonPrimitive.content == "sms.attachments" })
        val index = HostedPhoneFrames.encode(MessageIndex(7, (1L..1500L).toList()))!!.single()
        assertEquals(1000, index.getValue("ids").jsonArray.size)
        assertEquals(1500L, index.getValue("ids").jsonArray.first().jsonPrimitive.long)
        assertEquals("sms.remove", HostedPhoneFrames.encode(RemoveConversation(7))!!.single().getValue("type").jsonPrimitive.content)
        assertNull(HostedPhoneFrames.encode(PlaySound(true)))
    }

    /** The same literals are checked by the desktop in tests/test_hosted_phone.py. */
    @Test fun wireContractMatchesTheDesktop() {
        val thread = HostedPhoneFrames.encode(ConversationInfo(7, listOf("+15550100"), 99,
            TextMessage(41, listOf("+15550100"), "Synthetic hello", 1_760_000_000_000, messageType = 1, subscriptionId = 1)))!!.single()
        assertEquals(THREAD_WIRE, String(HostedEnvelope.canonical(thread), Charsets.US_ASCII))
        assertEquals(HostedPhoneCommand.SmsSend(7, "On my way 😀"), parse(SEND_WIRE))
    }

    @Test fun callStateCarriesNumberAndNameWithoutControlCharacters() {
        val ringing = HostedPhoneFrames.encode(CallInfo(CallState.Ringing, "+1555\u00000100", ContactInfo("1", "k", "Synthetic Caller", "+15550100")))!!.single()
        assertEquals(buildJsonObject { put("type", "call.state"); put("state", "ringing"); put("number", "+15550100"); put("name", "Synthetic Caller") }, ringing)
        assertEquals("missed", HostedPhoneFrames.encode(CallInfo(CallState.MissedCall, ""))!!.single().getValue("state").jsonPrimitive.content)
    }

    @Test fun answersShrinkToFitAndKeepTheirShape() {
        val contacts = List(30) { ContactInfo("$it", "k$it", "😀".repeat(200) + it, "+1555010$it") }
        val results = HostedPhoneFrames.contacts("😀", contacts)
        assertEquals(setOf("type", "query", "contacts"), keys(results))
        assertTrue(HostedPhoneFrames.fits(results))
        assertTrue(results.getValue("contacts").jsonArray.size in 1..20)
        val calls = List(60) { CallLogInfo(it.toLong(), "+1555010$it", it * 1000L, 5, CallLogType.Missed, ContactInfo("$it", "k", "😀".repeat(240), "")) }
        val log = HostedPhoneFrames.callLog(calls)
        assertEquals(setOf("type", "calls"), keys(log))
        assertTrue(HostedPhoneFrames.fits(log) && log.getValue("calls").jsonArray.size in 1..50)
        assertEquals(setOf("number", "name", "timestamp", "duration", "type"), keys(log.getValue("calls").jsonArray[0].jsonObject))
    }
}
