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
}
