package io.github.resticdroid.restic

import org.json.JSONObject

public sealed interface ResticEvent {
    public data class Progress(
        val percentDone: Double,
        val totalFiles: Long?,
        val filesDone: Long?,
        val totalBytes: Long?,
        val bytesDone: Long?,
        val secondsElapsed: Long?,
        val secondsRemaining: Long?,
        val currentFiles: List<String>,
    ) : ResticEvent

    public data class Summary(
        val snapshotId: String?,
        val filesNew: Long,
        val filesChanged: Long,
        val filesUnmodified: Long,
        val dirsNew: Long,
        val dirsChanged: Long,
        val dirsUnmodified: Long,
        val dataAdded: Long,
        val dataAddedPacked: Long,
        val totalFilesProcessed: Long,
        val totalBytesProcessed: Long,
        val totalDurationSeconds: Double,
    ) : ResticEvent

    public data class ItemError(val item: String?, val during: String?, val message: String) : ResticEvent

    public data class Json(val obj: JSONObject) : ResticEvent

    public data class Output(val line: String) : ResticEvent

    public data class Diagnostic(val line: String) : ResticEvent

    public data class Finished(val exitCode: Int) : ResticEvent
}

public object ResticExit {
    public const val OK: Int = 0
    public const val ERROR: Int = 1
    public const val GO_RUNTIME_ERROR: Int = 2
    public const val INCOMPLETE_BACKUP: Int = 3
    public const val REPOSITORY_NOT_FOUND: Int = 10
    public const val REPOSITORY_LOCK_FAILED: Int = 11
    public const val WRONG_PASSWORD: Int = 12
    public const val INTERRUPTED: Int = 130

    public fun describe(code: Int): String = when (code) {
        OK -> "success"
        ERROR -> "restic reported an error"
        GO_RUNTIME_ERROR -> "restic crashed"
        INCOMPLETE_BACKUP -> "backup completed, but some files could not be read"
        REPOSITORY_NOT_FOUND -> "repository does not exist"
        REPOSITORY_LOCK_FAILED -> "repository is locked by another run"
        WRONG_PASSWORD -> "wrong password"
        INTERRUPTED -> "interrupted"
        else -> "exit code $code"
    }

    public fun isSuccess(code: Int): Boolean = code == OK || code == INCOMPLETE_BACKUP
}
