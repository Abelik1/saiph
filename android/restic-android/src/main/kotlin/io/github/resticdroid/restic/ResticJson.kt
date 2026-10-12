package io.github.resticdroid.restic

import org.json.JSONArray
import org.json.JSONObject

internal object ResticJson {
    fun parseLine(line: String): ResticEvent? {
        val trimmed = line.trim()
        if (trimmed.isEmpty()) return null
        if (!trimmed.startsWith("{")) return ResticEvent.Output(line)

        val obj = runCatching { JSONObject(trimmed) }.getOrNull()
            ?: return ResticEvent.Output(line)

        return when (obj.optString("message_type")) {
            "status" -> progress(obj)
            "summary" -> summary(obj)
            "error" -> ResticEvent.ItemError(
                item = obj.optStringOrNull("item"),
                during = obj.optStringOrNull("during"),
                message = obj.optJSONObject("error")?.optString("message")
                    ?: obj.optString("error", "unknown error"),
            )
            else -> ResticEvent.Json(obj)
        }
    }

    // restic emits NDJSON. org.json stops silently after the first object,
    // so lines are parsed one at a time before any whole-document attempt.
    fun parseDocument(text: String): List<JSONObject> {
        val trimmed = text.trim()
        if (trimmed.isEmpty()) return emptyList()

        if (trimmed.startsWith("[")) {
            val array = runCatching { JSONArray(trimmed) }.getOrNull() ?: return emptyList()
            return (0 until array.length()).mapNotNull { array.optJSONObject(it) }
        }

        val lines = trimmed.lineSequence().map(String::trim).filter(String::isNotEmpty).toList()
        val perLine = lines.map { line -> runCatching { JSONObject(line) }.getOrNull() }
        if (perLine.isNotEmpty() && perLine.all { it != null }) {
            @Suppress("UNCHECKED_CAST")
            return perLine as List<JSONObject>
        }

        return runCatching { listOf(JSONObject(trimmed)) }.getOrDefault(emptyList())
    }

    private fun progress(o: JSONObject) = ResticEvent.Progress(
        percentDone = o.optDouble("percent_done", 0.0).let { if (it.isNaN()) 0.0 else it },
        totalFiles = o.optLongOrNull("total_files"),
        filesDone = o.optLongOrNull("files_done"),
        totalBytes = o.optLongOrNull("total_bytes"),
        bytesDone = o.optLongOrNull("bytes_done"),
        secondsElapsed = o.optLongOrNull("seconds_elapsed"),
        secondsRemaining = o.optLongOrNull("seconds_remaining"),
        currentFiles = o.optJSONArray("current_files")?.let { arr ->
            (0 until arr.length()).map { arr.optString(it) }
        } ?: emptyList(),
    )

    private fun summary(o: JSONObject) = ResticEvent.Summary(
        snapshotId = o.optStringOrNull("snapshot_id"),
        filesNew = o.optLong("files_new"),
        filesChanged = o.optLong("files_changed"),
        filesUnmodified = o.optLong("files_unmodified"),
        dirsNew = o.optLong("dirs_new"),
        dirsChanged = o.optLong("dirs_changed"),
        dirsUnmodified = o.optLong("dirs_unmodified"),
        dataAdded = o.optLong("data_added"),
        dataAddedPacked = o.optLong("data_added_packed"),
        totalFilesProcessed = o.optLong("total_files_processed"),
        totalBytesProcessed = o.optLong("total_bytes_processed"),
        totalDurationSeconds = o.optDouble("total_duration", 0.0).let { if (it.isNaN()) 0.0 else it },
    )

    private fun JSONObject.optStringOrNull(key: String): String? =
        if (isNull(key)) null else optString(key).ifEmpty { null }

    private fun JSONObject.optLongOrNull(key: String): Long? =
        if (has(key) && !isNull(key)) optLong(key) else null
}
