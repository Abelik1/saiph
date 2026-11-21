package com.orionmini.mobile

import com.castle.sefirah.BuildConfig
import org.junit.Assert.*
import org.junit.Test
import org.w3c.dom.Element
import java.io.File
import javax.xml.parsers.DocumentBuilderFactory

/**
 * The Google Play build is the website build with parts switched off, never a second app:
 * its source set holds one manifest that only removes entries (plus the launcher <queries>
 * that replace QUERY_ALL_PACKAGES), and the code tells the builds apart with
 * BuildConfig.PLAY_STORE alone. See docs/ANDROID_DISTRIBUTION.md.
 */
class StoreFlavorTest {
    private val tools = "http://schemas.android.com/tools"

    @Test fun playStoreFlagMatchesFlavor() {
        assertEquals(BuildConfig.FLAVOR == "play", BuildConfig.PLAY_STORE)
    }

    @Test fun flavorsHaveNoCodeOrResourcesOfTheirOwn() {
        assertEquals(listOf("AndroidManifest.xml"), File("src/play").list()!!.sorted())
        assertFalse(File("src/direct").exists())
        val gradle = File("build.gradle.kts").readText()
        assertFalse(Regex("""\b(play|direct)(Implementation|Api|CompileOnly|RuntimeOnly)\b""").containsMatchIn(gradle))
    }

    @Test fun playManifestOnlyRemoves() {
        val manifest = DocumentBuilderFactory.newInstance().apply { isNamespaceAware = true }
            .newDocumentBuilder().parse(File("src/play/AndroidManifest.xml")).documentElement
        manifest.children().forEach { child ->
            when (child.tagName) {
                "queries" -> child.children().forEach { assertEquals("intent", it.tagName) }
                "application" -> child.children().forEach { assertRemoves(it) }
                else -> assertRemoves(child)
            }
        }
    }

    private fun assertRemoves(element: Element) =
        assertEquals("<${element.tagName}> must be tools:node=\"remove\"", "remove", element.getAttributeNS(tools, "node"))

    private fun Element.children(): List<Element> =
        (0 until childNodes.length).map { childNodes.item(it) }.filterIsInstance<Element>()
}
