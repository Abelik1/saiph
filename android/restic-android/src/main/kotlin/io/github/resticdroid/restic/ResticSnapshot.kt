package io.github.resticdroid.restic

import org.json.JSONObject
import java.time.Instant
import java.time.OffsetDateTime

public data class ResticSnapshot(
    val id: String,
    val shortId: String,
    val time: String,
    val hostname: String,
    val username: String,
    val paths: List<String>,
    val tags: List<String>,
    val summary: SnapshotSummary?,
) {
    /**
     * When this snapshot was taken, for ordering.
     *
     * [time] is what restic wrote, offset and all, and comparing those strings
     * is not the same as comparing moments: Go pins the local zone to UTC on
     * Android, so a phone stamps 10:00:00Z where a desktop two zones east
     * stamps 11:00:00+03:00 for a moment an hour earlier. Sorted as text the
     * older one wins. Unparseable falls to the epoch, and so to the bottom of
     * a list sorted newest first.
     */
    public val instant: Instant
        get() = runCatching { OffsetDateTime.parse(time).toInstant() }.getOrDefault(Instant.EPOCH)

    public data class SnapshotSummary(
        val filesNew: Long,
        val filesChanged: Long,
        val totalFilesProcessed: Long,
        val totalBytesProcessed: Long,
        val dataAdded: Long,
    )

    public companion object {
        public fun from(o: JSONObject): ResticSnapshot {
            val id = o.optString("id")
            return ResticSnapshot(
                id = id,
                shortId = o.optString("short_id").ifEmpty { id.take(8) },
                time = o.optString("time"),
                hostname = o.optString("hostname"),
                username = o.optString("username"),
                paths = o.optJSONArray("paths")?.let { a -> (0 until a.length()).map { a.optString(it) } }.orEmpty(),
                tags = o.optJSONArray("tags")?.let { a -> (0 until a.length()).map { a.optString(it) } }.orEmpty(),
                summary = o.optJSONObject("summary")?.let { s ->
                    SnapshotSummary(
                        filesNew = s.optLong("files_new"),
                        filesChanged = s.optLong("files_changed"),
                        totalFilesProcessed = s.optLong("total_files_processed"),
                        totalBytesProcessed = s.optLong("total_bytes_processed"),
                        dataAdded = s.optLong("data_added"),
                    )
                },
            )
        }
    }
}
