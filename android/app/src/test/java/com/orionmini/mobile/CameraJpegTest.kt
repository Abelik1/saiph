// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import java.nio.ByteBuffer
import org.junit.Assert.*
import org.junit.Test

class CameraJpegTest {
    @Test fun packsPaddedLumaAndInterleavedChromaWithoutMovingSource() {
        val luma = ByteBuffer.wrap(byteArrayOf(99, 1, 2, 3, 4, 99, 99, 5, 6, 7, 8)).apply { position(1) }
        val v = ByteBuffer.wrap(byteArrayOf(21, 99, 22))
        val u = ByteBuffer.wrap(byteArrayOf(11, 99, 12))
        val nv21 = ByteArray(12)
        CameraJpeg.packPlane(luma, 6, 1, 4, 2, nv21, 0, 1)
        CameraJpeg.packPlane(v, 4, 2, 2, 1, nv21, 8, 2)
        CameraJpeg.packPlane(u, 4, 2, 2, 1, nv21, 9, 2)
        assertArrayEquals(byteArrayOf(1, 2, 3, 4, 5, 6, 7, 8, 21, 11, 22, 12), nv21)
        assertEquals(1, luma.position())
    }
    @Test fun handlesPlanarChromaWithRowPadding() {
        val result = ByteArray(8)
        CameraJpeg.packPlane(ByteBuffer.wrap(byteArrayOf(1, 2, 99, 3, 4)), 3, 1, 2, 2, result, 0, 2)
        assertArrayEquals(byteArrayOf(1, 0, 2, 0, 3, 0, 4, 0), result)
    }
}
