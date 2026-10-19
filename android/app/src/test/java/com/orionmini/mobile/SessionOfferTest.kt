// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class SessionOfferTest {
    /** The same synthetic vectors the desktop's tests/test_session_offer.py reads. */
    private val vectors = Json.parseToJsonElement(
        javaClass.classLoader!!.getResource("session-offer-vectors.json")!!.readText()).jsonObject
    private val now = vectors.getValue("now").jsonPrimitive.long

    @Test fun sharedVectorsMatchTheDesktop() {
        val cases = vectors.getValue("cases").jsonArray
        assertTrue(cases.size >= 20)
        for (case in cases.map { it.jsonObject }) {
            val name = case.getValue("name").jsonPrimitive.content
            val parsed = runCatching { SessionOffer.parse(case.getValue("payload").jsonObject, now) }
            assertEquals(name, case.getValue("valid").jsonPrimitive.boolean, parsed.isSuccess)
        }
    }

    private fun valid(): SessionOffer = SessionOffer.parse(vectors.getValue("cases").jsonArray.first().jsonObject.getValue("payload").jsonObject, now)

    @Test fun offerCarriesTheScannedProfile() {
        val offer = valid()
        assertEquals("camera", offer.service)
        assertEquals(1920, offer.camera.width); assertEquals(20, offer.camera.fps)
        assertEquals(offer.expiresAt, offer.camera.expires)
        assertTrue(runCatching { SessionOffer.parse(vectors.getValue("cases").jsonArray.first().jsonObject.getValue("payload").jsonObject, offer.expiresAt) }.isFailure)
    }

    @Test fun pendingOffersAreShownOnceAndTakenOnce() {
        SessionOffers.clear()
        val offer = valid()
        assertTrue(SessionOffers.put(offer, "Desk", "dev_a", now))
        assertFalse("replayed offer", SessionOffers.put(offer, "Desk", "dev_a", now))
        assertNotNull(SessionOffers.peek(offer.id, now))
        assertEquals("Desk", SessionOffers.take(offer.id, now)?.computer)
        assertNull("taken twice", SessionOffers.take(offer.id, now))
    }

    @Test fun pendingOffersExpireAndFollowTheRoster() {
        SessionOffers.clear()
        val offer = valid()
        assertTrue(SessionOffers.put(offer, "Desk", "dev_a", now))
        SessionOffers.retain(setOf("dev_b"))
        assertNull("revoked computer", SessionOffers.peek(offer.id, now))
        SessionOffers.clear()
        val other = SessionOffer(offer.id.replace('c', 'd'), offer.service, offer.expiresAt, offer.invite, offer.camera)
        assertTrue(SessionOffers.put(other, "Desk", "dev_a", now))
        assertNull("expired", SessionOffers.take(other.id, offer.expiresAt))
    }
}
