// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.*
import org.junit.Test

class HostedTrialTest {
    private val now = 1_800_000_000L
    private fun parse(json: String) = HostedTrial.parse(Json.parseToJsonElement(json).jsonObject)

    @Test fun trialDaysLeftRoundUpAndOfferToSubscribe() {
        val access = parse("""{"entitled":true,"until":${now + 86_401},"kinds":["trial"],"trial_until":${now + 86_401}}""")
        val notice = HostedTrial.notice(access, now)!!
        assertEquals("trial", notice.state)
        assertEquals(2, notice.daysLeft)
        assertEquals("Free trial: 2 days left", notice.title)
        assertEquals("Subscribe", notice.action)
        assertEquals("Free trial: 1 day left", HostedTrial.notice(access, now + 86_400)!!.title)
        assertFalse(HostedTrial.refused(access))
    }

    @Test fun anEndedTrialPausesCloudAndSaysNothingWasDeleted() {
        val access = parse("""{"entitled":false,"until":null,"kinds":[],"trial_until":${now - 10}}""")
        val notice = HostedTrial.notice(access, now)!!
        assertEquals("trial_ended", notice.state)
        assertTrue(notice.message.contains("Nothing was deleted"))
        assertTrue(HostedTrial.refused(access))
    }

    @Test fun anAccountWithoutAccessIsOfferedTheTrial() {
        val notice = HostedTrial.notice(parse("""{"entitled":false,"until":null,"kinds":[]}"""), now)!!
        assertEquals("none", notice.state)
        assertEquals("Start free trial or subscribe", notice.action)
    }

    @Test fun subscribersAndInvitationHoldersSeeNoNotice() {
        for (kinds in listOf("\"paid\"", "\"beta\"", "\"paid\",\"trial\"", "\"admin\""))
            assertNull(HostedTrial.notice(parse("""{"entitled":true,"until":${now + 99},"kinds":[$kinds],"trial_until":${now + 50}}"""), now))
        assertNull(HostedTrial.notice(null, now))
        assertFalse(HostedTrial.refused(null))
    }

    @Test fun anythingButTheExactShapeIsIgnored() {
        for (json in listOf(
            """{"entitled":true,"until":null,"kinds":["paid"]}""",
            """{"entitled":false,"until":$now,"kinds":[]}""",
            """{"entitled":true,"until":$now,"kinds":[]}""",
            """{"entitled":true,"until":$now,"kinds":["root"]}""",
            """{"entitled":true,"until":$now,"kinds":["paid","paid"]}""",
            """{"entitled":true,"until":"$now","kinds":["paid"]}""",
            """{"entitled":"true","until":$now,"kinds":["paid"]}""",
            """{"entitled":false,"until":null,"kinds":[],"trial_until":-1}""",
            """{"entitled":false,"until":null,"kinds":[],"extra":1}""",
        )) assertNull(json, parse(json))
    }
}
