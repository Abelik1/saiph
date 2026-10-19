// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

/** Camera and phone screen request prompts: surfaces, replacement and cleanup. Synthetic values only. */
class RequestPromptsTest {
    private val now = 1_800_000_000L
    private fun prompt(id: Char, service: String = "camera", expires: Long = now + 90) =
        RequestBoard.Prompt(id.toString().repeat(32), service, "Synthetic desk", expires)

    @Test fun foregroundAddsAPopUpToTheNotification() {
        val board = RequestBoard()
        assertEquals(RequestBoard.Plan(notify = true, popup = true, replaced = emptyList()), board.offer(prompt('a'), foreground = true, now = now))
        assertEquals(RequestBoard.Plan(notify = true, popup = false, replaced = emptyList()), board.offer(prompt('b', "screen"), foreground = false, now = now))
    }

    @Test fun aNewerRequestReplacesTheOlderOneForTheSameService() {
        val board = RequestBoard()
        board.offer(prompt('a'), true, now)
        board.offer(prompt('s', "screen"), true, now)
        val plan = board.offer(prompt('b'), true, now)
        assertEquals(listOf(prompt('a')), plan.replaced)
        assertEquals(prompt('b'), board.current("camera"))
        assertEquals(prompt('s', "screen"), board.current("screen"))
        // Closing the replaced offer touches nothing that is still shown.
        assertNull(board.close(prompt('a').id))
    }

    @Test fun expiredClosedTakenAndRevokedRequestsLeaveNoPrompt() {
        val board = RequestBoard()
        assertFalse(board.offer(prompt('x', expires = now), true, now).notify)  // Already expired: never shown.
        board.offer(prompt('a', expires = now + 10), true, now)
        board.offer(prompt('s', "screen", expires = now + 100), true, now)
        assertEquals(listOf(prompt('a', expires = now + 10)), board.expire(now + 10))
        assertNull(board.current("camera"))
        assertEquals(prompt('s', "screen", expires = now + 100), board.close(prompt('s').id))
        assertNull(board.current("screen"))
        board.offer(prompt('c'), true, now)
        assertEquals(listOf(prompt('c')), board.take("camera"))
        board.offer(prompt('d'), true, now)
        assertEquals(listOf(prompt('d')), board.retain(emptySet()))
        assertNull(board.popupCandidate(now))
    }

    @Test fun dismissingThePopUpKeepsTheNotificationButDoesNotPopUpAgain() {
        val board = RequestBoard()
        board.offer(prompt('a'), true, now)
        assertEquals(prompt('a'), board.popupCandidate(now))
        board.hide(prompt('a').id)
        assertNull(board.popupCandidate(now))
        assertEquals(prompt('a'), board.current("camera"))
        assertNull(board.popupCandidate(now + 91))  // Expired as well.
    }

    @Test fun copyNamesTheComputerAndTheRequest() {
        assertEquals("Synthetic desk wants to use your camera", RequestBoard.copy("camera", "Synthetic desk").first)
        assertEquals("Synthetic desk wants to show your screen", RequestBoard.copy("screen", "Synthetic desk").first)
        assertEquals("Your computer wants to use your camera", RequestBoard.copy("camera", "  ").first)
        assertEquals(40 + " wants to use your camera".length, RequestBoard.copy("camera", "x".repeat(80)).first.length)
    }

    @Test fun sessionCloseIsExactAndOnlyFromTheSendingComputer() {
        val id = "c".repeat(32)
        val close = buildJsonObject { put("type", "session.close"); put("version", 1); put("id", id) }
        assertEquals(id, SessionOffer.parseClose(close))
        assertNull(SessionOffer.parseClose(JsonObject(close + ("extra" to JsonPrimitive(1)))))
        assertNull(SessionOffer.parseClose(JsonObject(close + ("version" to JsonPrimitive(2)))))
        assertNull(SessionOffer.parseClose(JsonObject(close + ("version" to JsonPrimitive("1")))))
        assertNull(SessionOffer.parseClose(JsonObject(close + ("id" to JsonPrimitive("C".repeat(32))))))
        assertNull(SessionOffer.parseClose(JsonObject(close + ("type" to JsonPrimitive("session.offer")))))
    }

    @Test fun pendingOffersCloseOnlyForTheirOwnComputer() {
        SessionOffers.clear()
        val offer = SessionOffer("d".repeat(32), "camera", now + 60, "invite", null)
        assertTrue(SessionOffers.put(offer, "Desk", "dev_computer", now))
        assertNull(SessionOffers.close(offer.id, "dev_other", now))
        assertNotNull(SessionOffers.peek(offer.id, now))
        assertNotNull(SessionOffers.close(offer.id, "dev_computer", now))
        assertNull(SessionOffers.peek(offer.id, now))
        // Declined: gone, and its ID is still remembered so a replay does not prompt again.
        val second = SessionOffer("e".repeat(32), "screen", now + 60, "invite", null)
        assertTrue(SessionOffers.put(second, "Desk", "dev_computer", now))
        SessionOffers.decline(second.id)
        assertNull(SessionOffers.peek(second.id, now))
        assertFalse(SessionOffers.put(second, "Desk", "dev_computer", now))
        SessionOffers.clear()
    }
}
