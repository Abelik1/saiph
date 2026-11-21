// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class CloudWakeTest {
    private fun read(json: String) = CloudWake.read(Json.parseToJsonElement(json).jsonObject)

    @Test fun theMagicPacketIsSixMarkersThenTheAddressSixteenTimes() {
        val packet = CloudWake.packet("aa:bb:cc:dd:ee:01")
        assertEquals(102, packet.size)
        assertArrayEquals(ByteArray(6) { 0xFF.toByte() }, packet.copyOfRange(0, 6))
        val address = byteArrayOf(0xAA.toByte(), 0xBB.toByte(), 0xCC.toByte(), 0xDD.toByte(), 0xEE.toByte(), 0x01)
        for (copy in 0 until 16) assertArrayEquals(address, packet.copyOfRange(6 + copy * 6, 12 + copy * 6))
    }

    @Test fun onlyTheComputersExactShapeIsRead() {
        assertEquals(listOf("aa:bb:cc:dd:ee:01"), read("""{"type":"computer.wake","addresses":["aa:bb:cc:dd:ee:01"]}"""))
        assertNull(read("""{"type":"computer.wake","addresses":[]}"""))
        assertNull(read("""{"type":"computer.wake","addresses":["AA:BB:CC:DD:EE:01"]}"""))
        assertNull(read("""{"type":"computer.wake","addresses":["aa:bb:cc:dd:ee:01"],"host":"x"}"""))
        assertNull(read("""{"type":"computer.wake","addresses":["1","2","3","4","5"]}"""))
    }
}
