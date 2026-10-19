// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class LanFilesTest {
    /** The same synthetic vectors the desktop's tests/test_lan_files.py reads. */
    private val vectors = Json.parseToJsonElement(
        javaClass.classLoader!!.getResource("lan-file-vectors.json")!!.readText()).jsonObject
    private val offers = Json.parseToJsonElement(
        javaClass.classLoader!!.getResource("session-offer-vectors.json")!!.readText()).jsonObject
    private val now = vectors.getValue("now").jsonPrimitive.long

    @Test fun fileNamesMatchTheDesktop() {
        for (case in vectors.getValue("names").jsonArray.map { it.jsonObject }) {
            val name = case.getValue("name").jsonPrimitive.content
            assertEquals(name, case.getValue("valid").jsonPrimitive.boolean, LanFileFormat.validName(name))
        }
    }

    @Test fun uploadRequestsAndRefusalsMatchTheDesktop() {
        for (case in vectors.getValue("requests").jsonArray.map { it.jsonObject }) {
            val parsed = LanFileFormat.parseRequest(case.getValue("payload").jsonObject, now)
            assertEquals(case.getValue("name").jsonPrimitive.content, case.getValue("valid").jsonPrimitive.boolean, parsed != null)
        }
        for (case in vectors.getValue("refusals").jsonArray.map { it.jsonObject }) {
            val parsed = LanFileFormat.parseRefuse(case.getValue("payload").jsonObject)
            assertEquals(case.getValue("name").jsonPrimitive.content, case.getValue("valid").jsonPrimitive.boolean, parsed != null)
        }
    }

    private fun fileOffer(name: String): SessionOffer = SessionOffer.parse(offers.getValue("cases").jsonArray.map { it.jsonObject }
        .first { it.getValue("name").jsonPrimitive.content == name }.getValue("payload").jsonObject, now)

    @Test fun fileOffersCarryWhatTheReceiverVerifies() {
        val get = fileOffer("file get").file
        assertEquals("get", get.mode); assertEquals("", get.request)
        assertEquals("Synthetic holiday.mp4", get.name); assertEquals(524_288_000L, get.size); assertEquals("e".repeat(64), get.sha256)
        val put = fileOffer("file put for a phone request").file
        assertEquals("put", put.mode); assertEquals("d".repeat(32), put.request)
        assertEquals("Résumé 2026 🎉.pdf", put.name); assertEquals(0L, put.size)
        assertEquals(1L shl 40, fileOffer("file largest size").file.size)
        assertTrue(runCatching { fileOffer("file get").camera }.isFailure)
    }

    @Test fun requestsAreFreshAndBounded() {
        val first = LanFileFormat.request("Synthetic phone video.mp4", 524_288_000, "f".repeat(64), now)
        val second = LanFileFormat.request("Synthetic phone video.mp4", 524_288_000, "f".repeat(64), now)
        assertNotEquals(first["id"], second["id"])
        assertEquals(now + 100, first.getValue("expires_at").jsonPrimitive.long)
        assertTrue(runCatching { LanFileFormat.request("a/b", 1, "f".repeat(64), now) }.isFailure)
        assertTrue(runCatching { LanFileFormat.request("ok.bin", LanFileFormat.MAX_BYTES + 1, "f".repeat(64), now) }.isFailure)
        assertEquals("storage" to "storage", LanFileFormat.parseRefuse(LanFileFormat.refuse("c".repeat(32), "storage"))!!.let { it.second to "storage" })
        assertEquals("c".repeat(32), SessionOffer.parseClose(SessionOffer.closePayload("c".repeat(32))))
    }

    @Test fun sharedNamesBecomeNamesBothPlatformsAccept() {
        assertEquals("Holiday_ day 1_2.mp4", LanFileFormat.safeName("Holiday: day 1/2.mp4"))
        assertEquals("trailing", LanFileFormat.safeName("trailing. "))
        assertEquals("shared-file", LanFileFormat.safeName("CON"))
        assertEquals("shared-file", LanFileFormat.safeName(""))
        val long = LanFileFormat.safeName("é".repeat(200) + ".bin")
        assertTrue(LanFileFormat.validName(long) && long.toByteArray().size <= 255)
        assertEquals("emoji 🎉.png", LanFileFormat.safeName("emoji 🎉.png"))
    }

    @Test fun largeFileWordingSaysWhatLetsItThrough() {
        assertEquals("Synthetic laptop didn't answer on your network. Saiph Cloud sends files up to 19.9 MB and this file is 500.0 MB, " +
            "so both devices must be on the same Wi-Fi or network with Saiph open. Nothing was sent.",
            HostedTransferText.needsNetwork(500L * 1024 * 1024, "Synthetic laptop"))
        assertTrue(HostedTransferText.noNetwork(25L * 1024 * 1024).startsWith("Saiph Cloud sends files up to 19.9 MB. This file is 25.0 MB:"))
        assertEquals("Sending a.bin to Desk directly · 50%", HostedTransferText.sending("a.bin", "Desk", 5, 10, false))
    }
}
