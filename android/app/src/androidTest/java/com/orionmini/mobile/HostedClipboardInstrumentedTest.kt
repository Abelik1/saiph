// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.graphics.Bitmap
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import sefirah.network.orion.HostedClipboardImages
import java.io.File

/** Android codecs on synthetic files only; execute on a disposable test emulator. */
@RunWith(AndroidJUnit4::class)
class HostedClipboardInstrumentedTest {
    @Test fun actualCodecsAndMalformedImagesRespectLimits() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        assertFalse(context.getSharedPreferences("orion_hosted", 0).contains("device_id"))
        val file = File.createTempFile("clipboard-codec-test-", ".tmp", context.cacheDir)
        val bitmap = Bitmap.createBitmap(4, 3, Bitmap.Config.ARGB_8888).apply { eraseColor(0x80214263.toInt()) }
        try {
            for ((format, mime) in listOf(Bitmap.CompressFormat.PNG to "image/png", Bitmap.CompressFormat.JPEG to "image/jpeg", Bitmap.CompressFormat.WEBP_LOSSLESS to "image/webp")) {
                file.outputStream().use { assertTrue(bitmap.compress(format, 100, it)) }
                assertTrue(HostedClipboardImages.valid(mime, file))
                assertFalse(HostedClipboardImages.valid(if (mime == "image/png") "image/jpeg" else "image/png", file))
                file.writeBytes(file.readBytes().take(12).toByteArray())
                assertFalse(HostedClipboardImages.valid(mime, file))
            }
            file.writeText("synthetic malformed image")
            assertFalse(HostedClipboardImages.valid("image/png", file))
        } finally { bitmap.recycle(); file.delete() }
    }
}
