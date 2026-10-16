// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.content.ContentUris
import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.ImageDecoder
import android.os.Build
import android.provider.MediaStore
import kotlinx.serialization.json.*
import sefirah.network.orion.OrionPermissions
import java.io.ByteArrayOutputStream
import java.util.Base64

/** Bounded recent-photo previews, only after opt-in, permission and device approval. */
internal class HostedPhotos(private val context: Context, private val runtime: HostedRuntime) {
    private var revision = -1
    private var next = 0L
    private var items = emptyList<JsonObject>()
    private val sent = mutableMapOf<String, List<JsonObject>>()

    suspend fun refresh(connected: Boolean) {
        if (revision != runtime.photosRevision) { next = 0; revision = runtime.photosRevision }
        if (!runtime.photosShared() || !OrionPermissions.read(context).photos || !connected) {
            items = emptyList(); sent.clear(); next = 0; return
        }
        val subscribers = runtime.subscribers().keys
        sent.keys.retainAll(subscribers)
        if (subscribers.isEmpty()) return
        if (System.currentTimeMillis() >= next) {
            items = readItems(); next = System.currentTimeMillis() + 120_000
        }
        for (device in subscribers) {
            val previous = sent[device]
            if (previous == items) continue
            var queued = true
            for (item in items) if (previous?.contains(item) != true)
                queued = runtime.enqueuePhone(device, item) {} && queued
            val index = buildJsonObject {
                put("type", "photos.sync"); put("ids", JsonArray(items.map { it.getValue("id") }))
            }
            queued = runtime.enqueuePhone(device, index) {} && queued
            if (queued) sent[device] = items
        }
    }
    internal fun readItems(): List<JsonObject> {
        if (!runtime.photosShared() || !OrionPermissions.read(context).photos) return emptyList()
        val found = mutableListOf<JsonObject>()
        context.contentResolver.query(MediaStore.Images.Media.EXTERNAL_CONTENT_URI,
            arrayOf(MediaStore.Images.Media._ID, MediaStore.Images.Media.DISPLAY_NAME, MediaStore.Images.Media.DATE_ADDED),
            null, null, "${MediaStore.Images.Media.DATE_ADDED} DESC")?.use { cursor ->
            while (found.size < 100 && cursor.moveToNext()) {
                if (!runtime.photosShared() || !OrionPermissions.read(context).photos) return emptyList()
                val id = cursor.getLong(0)
                if (id <= 0 || id > 9_007_199_254_740_991L) continue
                val uri = ContentUris.withAppendedId(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, id)
                runCatching {
                    // MediaStore may return a tiny cached thumbnail regardless of
                    // the requested Size. Decode the permitted image at a bounded
                    // target instead; never allocate the full-resolution bitmap.
                    val bitmap = if (Build.VERSION.SDK_INT >= 28) ImageDecoder.decodeBitmap(ImageDecoder.createSource(context.contentResolver, uri)) { decoder, info, _ ->
                        val scale = minOf(1.0, 384.0 / maxOf(info.size.width, info.size.height))
                        decoder.setTargetSize((info.size.width * scale).toInt().coerceAtLeast(1), (info.size.height * scale).toInt().coerceAtLeast(1))
                        decoder.allocator = ImageDecoder.ALLOCATOR_SOFTWARE
                    } else {
                        val options = BitmapFactory.Options().apply { inJustDecodeBounds = true }
                        context.contentResolver.openInputStream(uri)!!.use { BitmapFactory.decodeStream(it, null, options) }
                        check(options.outWidth > 0 && options.outHeight > 0)
                        options.inJustDecodeBounds = false
                        options.inSampleSize = 1
                        while (maxOf(options.outWidth, options.outHeight).toLong() / (options.inSampleSize * 2L) >= 384) options.inSampleSize *= 2
                        context.contentResolver.openInputStream(uri)!!.use { BitmapFactory.decodeStream(it, null, options) }
                    } ?: return@runCatching
                    val bytes = try { preview(bitmap) } finally { bitmap.recycle() }
                    found += buildJsonObject {
                        put("type", "photos.item"); put("id", id.toString())
                        put("name", sefirah.network.orion.HostedPhoneFrames.clean(cursor.getString(1) ?: "Photo.jpg", 180))
                        put("timestamp", cursor.getLong(2).coerceIn(0, 253_402_300_799L) * 1000)
                        put("preview", "data:image/jpeg;base64," + Base64.getEncoder().encodeToString(bytes))
                    }
                }
            }
        }
        return found
    }

    /** Sharper grid previews without increasing the sealed frame or memory limits. */
    internal fun preview(bitmap: Bitmap): ByteArray {
        var edge = minOf(384, maxOf(bitmap.width, bitmap.height))
        while (true) {
            val scale = edge.toDouble() / maxOf(bitmap.width, bitmap.height)
            val small = Bitmap.createScaledBitmap(bitmap, (bitmap.width * scale).toInt().coerceAtLeast(1),
                (bitmap.height * scale).toInt().coerceAtLeast(1), true)
            try {
                for (quality in listOf(75, 65, 55)) {
                    val bytes = ByteArrayOutputStream().apply { check(small.compress(Bitmap.CompressFormat.JPEG, quality, this)) }.toByteArray()
                    if (bytes.size <= 12_000) return bytes
                }
            } finally { if (small !== bitmap) small.recycle() }
            check(edge > 96)
            edge = maxOf(96, edge * 3 / 4)
        }
    }
}
