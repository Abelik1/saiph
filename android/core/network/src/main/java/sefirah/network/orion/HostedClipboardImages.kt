// SPDX-License-Identifier: GPL-3.0-only
package sefirah.network.orion

import android.graphics.BitmapFactory
import java.io.File

/** Limits apply before a full decode or streaming encryption. No image metadata is logged. */
object HostedClipboardImages {
    const val MAX_BYTES = 16 * 1024 * 1024
    const val MAX_PIXELS = 16_000_000L
    val extensions = mapOf("image/png" to "png", "image/jpeg" to "jpg", "image/webp" to "webp")
    fun dimensions(width: Int, height: Int) = width > 0 && height > 0 && width.toLong() * height <= MAX_PIXELS
    fun valid(mime: String, file: File): Boolean = runCatching {
        if (mime !in extensions || !file.isFile || file.length() !in 1..MAX_BYTES.toLong()) return false
        val options = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(file.path, options)
        if (options.outMimeType != mime || !dimensions(options.outWidth, options.outHeight)) return false
        val bitmap = BitmapFactory.decodeFile(file.path) ?: return false
        bitmap.recycle()
        true
    }.getOrDefault(false)
}
