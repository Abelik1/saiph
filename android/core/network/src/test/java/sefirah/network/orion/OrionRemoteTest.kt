package sefirah.network.orion

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class OrionRemoteTest {
    private fun json(value: String) = Json.parseToJsonElement(value).jsonObject
    @Test fun catalogsParseIntoFixedControls() {
        val apps = OrionRemote.parse(json("""{"apps":[{"id":"keyboard","name":"Type","available":true,"controls":[{"id":"type","label":"Text","kind":"text","max":500},{"id":"enter","label":"Enter","kind":"button"}]}]}"""))
        assertEquals(listOf(RemoteControl("type", "Text", "text", 500), RemoteControl("enter", "Enter", "button", 500)), apps.single().controls)
    }
    @Test fun touchpadControlsAndMovementAreBounded() {
        val apps = OrionRemote.parse(json("""{"apps":[{"id":"touchpad","name":"Touchpad","available":true,"controls":[{"id":"move","label":"Move","kind":"pad"}]}]}"""))
        assertEquals("pad", apps.single().controls.single().kind)
        val move = OrionRemote.pad("touchpad", "move", 9000, -5)
        assertEquals(2000, move.getValue("dx").jsonPrimitive.int)
        assertEquals(-5, move.getValue("dy").jsonPrimitive.int)
    }
    @Test fun malformedCatalogsAreRefused() {
        for (bad in listOf("""{"apps":[{"id":"Media","name":"M","available":true,"controls":[]}]}""",
                """{"apps":[{"id":"media","name":"M","available":true,"controls":[{"id":"x","label":"X","kind":"script"}]}]}""",
                """{"apps":[{"id":"media","name":"M","available":true,"controls":[],"url":"https://example.invalid"}]}""",
                """{"apps":[],"extra":1}""")) {
            try { OrionRemote.parse(json(bad)); fail(bad) } catch (_: IllegalArgumentException) {}
        }
    }
    @Test fun resultsAndCatalogsAreKeptPerComputer() {
        assertTrue(OrionRemote.receive(json("""{"type":"remote.catalog","source":"desktop","payload":{"apps":[]}}""")))
        assertTrue(OrionRemote.receive(json("""{"type":"remote.result","source":"desktop","payload":{"app":"media","control":"next","ok":false,"message":"Bring it to the front"}}""")))
        assertFalse(OrionRemote.receive(json("""{"type":"handoff","source":"desktop","payload":{}}""")))
        assertEquals(emptyList<RemoteApp>(), OrionRemote.catalogs.value["desktop"])
        assertEquals("Bring it to the front", OrionRemote.result.value?.message)
    }
}
