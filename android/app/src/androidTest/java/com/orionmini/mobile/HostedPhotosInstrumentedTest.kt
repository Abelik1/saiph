// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.Manifest
import android.content.ContentValues
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.provider.MediaStore
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.util.Base64
import java.util.UUID

/** Real MediaStore and Android permissions; only a synthetic image in a disposable emulator. */
@RunWith(AndroidJUnit4::class)
class HostedPhotosInstrumentedTest {
    @Test fun photoIndexNeedsPermissionAndOptInAndUsesBoundedJpegPreviews() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val runtime = HostedRuntime.get(context)
        assertFalse(context.getSharedPreferences("orion_hosted", 0).contains("device_id"))
        assertFalse(HostedAccount.get(context).signedIn())
        val values = ContentValues().apply {
            put(MediaStore.Images.Media.DISPLAY_NAME, "Saiph-synthetic-${UUID.randomUUID()}.png")
            put(MediaStore.Images.Media.MIME_TYPE, "image/png")
            put(MediaStore.Images.Media.RELATIVE_PATH, "Pictures/SaiphSyntheticChecks")
            put(MediaStore.Images.Media.IS_PENDING, 1)
        }
        val uri = context.contentResolver.insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values)!!
        try {
            val bitmap = Bitmap.createBitmap(240, 120, Bitmap.Config.ARGB_8888).apply { eraseColor(0xff448866.toInt()) }
            context.contentResolver.openOutputStream(uri)!!.use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
            bitmap.recycle()
            context.contentResolver.update(uri, ContentValues().apply { put(MediaStore.Images.Media.IS_PENDING, 0) }, null, null)
            val photos = HostedPhotos(context, runtime)
            runtime.setPhotosShared(false)
            assertTrue(photos.readItems().isEmpty())
            runtime.setPhotosShared(true)
            assertTrue(photos.readItems().isEmpty())
            instrumentation.uiAutomation.grantRuntimePermission(context.packageName, Manifest.permission.READ_MEDIA_IMAGES)
            val row = photos.readItems().single { it.getValue("id").jsonPrimitive.content == uri.lastPathSegment }
            val bytes = Base64.getDecoder().decode(row.getValue("preview").jsonPrimitive.content.substringAfter(','))
            assertTrue(bytes.size <= 12_000)
            val preview = BitmapFactory.decodeByteArray(bytes, 0, bytes.size)!!
            assertEquals(96, preview.width)
            assertEquals(48, preview.height)
            preview.recycle()
            runtime.setPhotosShared(false)
            assertTrue(photos.readItems().isEmpty())
        } finally {
            runtime.setPhotosShared(false)
            context.contentResolver.delete(uri, null, null)
        }
    }
}
