// SPDX-License-Identifier: GPL-3.0-only
package sefirah.network.orion

import kotlinx.serialization.json.*
import sefirah.domain.model.PlaybackInfo
import sefirah.domain.model.PlaybackInfoType

/**
 * The phone's media sessions as one `media.state` list. Upstream sends full session info,
 * then partial play/position updates; they are merged here. Artwork is not sent.
 */
class OrionMedia {
    private val sessions = linkedMapOf<String, PlaybackInfo>()

    /** Returns the new state to publish, or null when nothing visible changed. */
    @Synchronized fun update(info: PlaybackInfo): JsonObject? {
        val before = state()
        when (info.infoType) {
            PlaybackInfoType.RemovedSession -> sessions.remove(info.source)
            PlaybackInfoType.PlaybackInfo -> sessions[info.source] = info
            PlaybackInfoType.PlaybackUpdate -> sessions[info.source]?.let { sessions[info.source] = it.copy(isPlaying = info.isPlaying, position = info.position) }
            PlaybackInfoType.TimelineUpdate -> sessions[info.source]?.let { sessions[info.source] = it.copy(position = info.position) }
        }
        return state().takeIf { it != before }
    }

    /** Drops sessions whose app is no longer active. */
    @Synchronized fun retain(active: Set<String>): JsonObject? {
        val before = state()
        sessions.keys.retainAll(active)
        return state().takeIf { it != before }
    }

    // Position is left out of change detection, so a playing track does not publish every tick.
    @Synchronized fun state(withPosition: Boolean = false): JsonObject = buildJsonObject {
        put("sessions", JsonArray(sessions.values.toList().takeLast(5).map { session(it, withPosition) }))
    }

    companion object {
        fun session(info: PlaybackInfo, withPosition: Boolean = true) = buildJsonObject {
            put("source", info.source.take(240)); put("app", (info.appName ?: "").take(120))
            put("title", (info.trackTitle ?: "").take(240)); put("artist", (info.artist ?: "").take(240))
            put("playing", info.isPlaying)
            put("can_play", info.canPlay ?: true); put("can_pause", info.canPause ?: true)
            put("can_next", info.canGoNext ?: false); put("can_previous", info.canGoPrevious ?: false); put("can_seek", info.canSeek ?: false)
            put("position_ms", if (withPosition) info.position.toLong().coerceIn(0, 1L shl 40) else 0)
            put("length_ms", info.maxSeekTime.toLong().coerceIn(0, 1L shl 40))
            put("volume", info.volume.coerceIn(0, 100))
        }
    }
}
