package sefirah.transfer.util

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import sefirah.domain.model.FileMetadata
import java.text.DecimalFormat

fun getFileMetadata(context: Context, uri: Uri): FileMetadata {
    var fileName = ""
    var fileSize: Long = 0

    context.contentResolver.query(uri, null, null, null, null)?.use { cursor ->
        val nameIndex = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
        val sizeIndex = cursor.getColumnIndex(OpenableColumns.SIZE)

        if (cursor.moveToFirst()) {
            if (nameIndex != -1) {
                fileName = cursor.getString(nameIndex)
            }
            if (sizeIndex != -1) {
                fileSize = cursor.getLong(sizeIndex)
            }
        }
    }

    val mimeType = context.contentResolver.getType(uri) ?: "application/octet-stream"

    return FileMetadata(fileName, mimeType, fileSize)
}

fun formatSize(size: Long): String {
    val kilo = 1024.0
    val mega = kilo * 1024
    val giga = mega * 1024

    val formatter = DecimalFormat("#.##")

    return when {
        size >= giga -> "${formatter.format(size / giga)} GB"
        size >= mega -> "${formatter.format(size / mega)} MB"
        else -> "${formatter.format(size / kilo)} KB"
    }
}
