// SPDX-License-Identifier: GPL-3.0-only
package sefirah.network.orion

import android.content.ContentUris
import android.content.Context
import android.net.Uri

/** One MMS part a computer asked for; used by the Hub's direct transfer and Saiph Cloud's sealed attachment. */
object MmsParts {
    data class Part(val uri: Uri, val name: String, val mime: String)

    /** The part, only when it belongs to [message] in [thread]; throws otherwise. */
    fun find(context: Context, thread: Long, message: Long, part: Long): Part {
        val (mid, mime, name) = context.contentResolver.query(Uri.parse("content://mms/part"), arrayOf("mid", "ct", "name", "cl"),
            "_id = ?", arrayOf(part.toString()), null)?.use {
            require(it.moveToFirst()); Triple(it.getLong(0), it.getString(1) ?: "application/octet-stream", it.getString(2) ?: it.getString(3) ?: "attachment_$part")
        } ?: throw IllegalStateException()
        require(mid == message)
        val owner = context.contentResolver.query(ContentUris.withAppendedId(Uri.parse("content://mms"), message), arrayOf("thread_id"), null, null, null)
            ?.use { if (it.moveToFirst()) it.getLong(0) else null }
        require(owner == thread)
        return Part(ContentUris.withAppendedId(Uri.parse("content://mms/part"), part), name, mime)
    }

    /** A file name and MIME type every receiver accepts (the desktop checks both strictly). */
    fun safeName(name: String, part: Long): String =
        name.replace(Regex("[^A-Za-z0-9._ -]"), "_").take(180).trim(' ', '.').ifEmpty { "attachment_$part" }
    fun safeMime(mime: String): String = mime.lowercase().substringBefore(';').trim()
        .takeIf { Regex("[a-z0-9.+-]{1,63}/[a-z0-9.+-]{1,63}").matches(it) } ?: "application/octet-stream"
}
