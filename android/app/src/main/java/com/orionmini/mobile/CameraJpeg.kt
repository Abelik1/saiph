// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.graphics.ImageFormat
import android.graphics.Rect
import android.graphics.YuvImage
import androidx.camera.core.ImageProxy
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer

/** Reuse the YUV workspace; avoid YUV -> RGB bitmap -> YUV for each JPEG. */
internal class CameraJpeg {
    private var pixels = ByteArray(0)
    private val output = ByteArrayOutputStream(256 * 1024)

    fun encode(image: ImageProxy, quality: Int): ByteArray {
        val width = image.width; val height = image.height
        require(width > 0 && height > 0 && width % 2 == 0 && height % 2 == 0
            && width <= 1920 && height <= 1920 && width * height <= 1920 * 1080)
        val size = width * height * 3 / 2
        if (pixels.size != size) pixels = ByteArray(size)
        val planes = image.planes
        require(planes.size == 3)
        packPlane(planes[0].buffer, planes[0].rowStride, planes[0].pixelStride, width, height, pixels, 0, 1)
        packPlane(planes[2].buffer, planes[2].rowStride, planes[2].pixelStride, width / 2, height / 2, pixels, width * height, 2)
        packPlane(planes[1].buffer, planes[1].rowStride, planes[1].pixelStride, width / 2, height / 2, pixels, width * height + 1, 2)
        output.reset()
        check(YuvImage(pixels, ImageFormat.NV21, width, height, null)
            .compressToJpeg(Rect(0, 0, width, height), quality, output))
        return output.toByteArray()
    }

    companion object {
        internal fun packPlane(source: ByteBuffer, rowStride: Int, pixelStride: Int, width: Int, height: Int,
            target: ByteArray, offset: Int, step: Int) {
            val buffer = source.duplicate()
            val base = buffer.position()
            for (row in 0 until height) {
                val start = base + row * rowStride
                val destination = offset + row * width * step
                if (pixelStride == 1 && step == 1) {
                    buffer.position(start); buffer.get(target, destination, width)
                } else {
                    for (column in 0 until width) target[destination + column * step] = buffer.get(start + column * pixelStride)
                }
            }
        }
    }
}
