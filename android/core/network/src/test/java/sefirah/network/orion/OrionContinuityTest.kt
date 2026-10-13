package sefirah.network.orion

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import java.time.Instant

class OrionContinuityTest {
    private fun plan() = Json.parseToJsonElement("""{"enabled":true,"timezone":"Europe/London","start_hour":23,"start_minute":0,"end_hour":7,"end_minute":0}""").jsonObject
    @Test fun overnightAndDstAreLocalTime() {
        assertTrue(OrionContinuity.active(plan(), Instant.parse("2026-06-01T22:00:00Z")))
        assertTrue(OrionContinuity.active(plan(), Instant.parse("2026-12-01T23:00:00Z")))
        assertFalse(OrionContinuity.active(plan(), Instant.parse("2026-06-02T06:00:00Z")))
        assertTrue(OrionContinuity.active(plan(), Instant.parse("2026-10-25T01:30:00Z")))
    }
    @Test fun malformedSchedulesAreRefused() {
        try { OrionContinuity.validatePlan(JsonObject(plan() + ("start_hour" to JsonPrimitive(24)))); fail() } catch (_: IllegalArgumentException) {}
        assertFalse(OrionContinuity.active(JsonObject(plan() + ("enabled" to JsonPrimitive(false))), Instant.parse("2026-06-01T23:00:00Z")))
    }
    @Test fun onlyOwnerChangesAreShared() {
        // Saiph's own rule turning DND on matches the expected state.
        assertFalse(OrionContinuity.shouldShare(system = true, expected = true, shared = true))
        // The owner turns DND on, or turns off DND that another device shared.
        assertTrue(OrionContinuity.shouldShare(system = true, expected = false, shared = null))
        assertTrue(OrionContinuity.shouldShare(system = false, expected = true, shared = true))
        // Already the shared state: nothing new to send.
        assertFalse(OrionContinuity.shouldShare(system = false, expected = true, shared = false))
        assertFalse(OrionContinuity.shouldShare(system = false, expected = false, shared = null))
    }
    @Test fun malformedDoNotDisturbStatesAreRefused() {
        OrionContinuity.validateDnd(Json.parseToJsonElement("""{"active":true,"changed_at":1800000000}""").jsonObject)
        for (bad in listOf("""{"active":"true","changed_at":1}""", """{"active":true}""", """{"active":true,"changed_at":1.5}""",
                """{"active":true,"changed_at":"5"}""", """{"active":true,"changed_at":0}""", """{"active":true,"changed_at":1,"until":2}""")) {
            try { OrionContinuity.validateDnd(Json.parseToJsonElement(bad).jsonObject); fail(bad) } catch (_: IllegalArgumentException) {}
        }
    }
}
