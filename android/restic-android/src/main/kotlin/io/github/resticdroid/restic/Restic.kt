package io.github.resticdroid.restic

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.channels.ProducerScope
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.buffer
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.runInterruptible
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.File
import java.io.IOException
import java.util.concurrent.TimeUnit

public class Restic internal constructor(
    private val binary: File,
    private val home: File,
    private val cache: File,
    private val temp: File,
    private val version: String,
    private val licence: String = "",
) {
    public fun bundledVersion(): String = version

    public fun bundledLicence(): String = licence

    public fun isAvailable(): Boolean = binary.canExecute()

    public fun stream(repository: ResticRepository?, command: ResticCommand): Flow<ResticEvent> =
        callbackFlow {
            val process = start(repository, command)

            val pumps = listOf(
                launch(Dispatchers.IO) {
                    pump(process.inputStream) { line ->
                        if (command.json) {
                            ResticJson.parseLine(line)
                        } else {
                            line.takeIf { it.isNotBlank() }?.let(ResticEvent::Output)
                        }
                    }
                },
                launch(Dispatchers.IO) {
                    pump(process.errorStream) { line ->
                        line.takeIf { it.isNotBlank() }?.let(ResticEvent::Diagnostic)
                    }
                },
            )

            launch(Dispatchers.IO) {
                val code = runInterruptible { process.waitFor() }
                pumps.forEach { it.join() }
                send(ResticEvent.Finished(code))
                close()
            }

            awaitClose { terminate(process) }
        }
            .buffer(BUFFERED_EVENTS)
            .flowOn(Dispatchers.IO)

    public suspend fun execute(
        repository: ResticRepository?,
        command: ResticCommand,
    ): ResticResult = withContext(Dispatchers.IO) {
        val process = start(repository, command)
        try {
            coroutineScope {
                val out = async { process.inputStream.bufferedReader().use { it.readText() } }
                val err = async { process.errorStream.bufferedReader().use { it.readText() } }
                val code = runInterruptible { process.waitFor() }
                ResticResult(code, out.await(), err.await())
            }
        } finally {
            terminate(process)
        }
    }

    public suspend fun executeJson(
        repository: ResticRepository?,
        command: ResticCommand,
    ): List<JSONObject> {
        val result = execute(repository, command)
        result.throwIfFailed()
        return ResticJson.parseDocument(result.stdout)
    }

    private suspend fun ProducerScope<ResticEvent>.pump(
        stream: java.io.InputStream,
        transform: (String) -> ResticEvent?,
    ) {
        stream.bufferedReader().use { reader ->
            while (currentCoroutineContext().isActive) {
                val line = reader.readLineBounded(MAX_LINE_CHARS) ?: break
                // send, not trySend: a measured run dropped 4731 of 5001 events,
                // including the terminal Finished one.
                transform(line)?.let { send(it) }
            }
        }
    }

    private fun java.io.BufferedReader.readLineBounded(limit: Int): String? {
        val builder = StringBuilder()
        var truncated = false
        while (true) {
            val c = read()
            when {
                c < 0 -> return if (builder.isEmpty() && !truncated) null else builder.finish(truncated)
                c == '\n'.code -> return builder.finish(truncated)
                c == '\r'.code -> Unit
                builder.length < limit -> builder.append(c.toChar())
                else -> truncated = true
            }
        }
    }

    private fun StringBuilder.finish(truncated: Boolean): String =
        if (truncated) "$this… (truncated)" else toString()

    private fun start(repository: ResticRepository?, command: ResticCommand): Process {
        if (!binary.canExecute()) {
            throw ResticException(
                "restic binary is not executable at ${binary.absolutePath}. " +
                    "This almost always means the APK was built without " +
                    "extractNativeLibs=true (see the :restic-android manifest)."
            )
        }
        listOf(home, cache, temp).forEach { it.mkdirs() }

        val argv = buildList {
            add(binary.absolutePath)
            // The repository goes in the environment, never in argv: for a REST
            // repository the URI carries the user's password, and argv is world
            // readable through /proc.
            if (repository != null) addAll(repository.options)
            addAll(command.args)
        }

        val builder = ProcessBuilder(argv)
        builder.directory(home)

        val env = builder.environment()
        env.clear()
        env["HOME"] = home.absolutePath
        env["TMPDIR"] = temp.absolutePath
        env["XDG_CACHE_HOME"] = cache.parentFile?.absolutePath ?: cache.absolutePath
        env["RESTIC_CACHE_DIR"] = cache.absolutePath
        env["PATH"] = "/system/bin:/system/xbin"
        env["RESTIC_PROGRESS_FPS"] = "1"
        if (repository != null) {
            // Backend credentials first, so a repository that named RESTIC_PASSWORD
            // or RESTIC_REPOSITORY itself cannot displace the real ones.
            env.putAll(repository.env)
            env["RESTIC_REPOSITORY"] = repository.uri
            env["RESTIC_PASSWORD"] = repository.password
        }

        return try {
            builder.start()
        } catch (e: IOException) {
            throw ResticException("could not start restic: ${e.message}", e)
        }
    }

    private fun terminate(process: Process) {
        if (!process.isAlive) return
        process.destroy()
        if (!process.waitFor(GRACE_SECONDS, TimeUnit.SECONDS)) {
            process.destroyForcibly()
        }
    }

    public companion object {
        private const val BUFFERED_EVENTS = 256
        private const val MAX_LINE_CHARS = 64 * 1024
        private const val GRACE_SECONDS = 10L

        @JvmStatic
        public fun from(context: Context): Restic {
            val app = context.applicationContext
            val binary = File(app.applicationInfo.nativeLibraryDir, BINARY_NAME)
            fun raw(id: Int): String = runCatching {
                app.resources.openRawResource(id).bufferedReader().use { it.readText().trim() }
            }.getOrDefault("")

            return Restic(
                binary = binary,
                home = File(app.filesDir, "restic"),
                cache = File(app.cacheDir, "restic"),
                temp = File(app.cacheDir, "restic-tmp"),
                version = raw(R.raw.restic_version).ifEmpty { "unknown" },
                licence = raw(R.raw.restic_license),
            )
        }

        internal const val BINARY_NAME: String = "librestic.so"
    }
}

public data class ResticResult(
    val exitCode: Int,
    val stdout: String,
    val stderr: String,
) {
    public val isSuccess: Boolean get() = ResticExit.isSuccess(exitCode)

    public fun throwIfFailed(): ResticResult = apply {
        if (!isSuccess) throw ResticException(humanError(), exitCode = exitCode)
    }

    private fun messages(): Sequence<JSONObject> =
        (stdout.lineSequence() + stderr.lineSequence())
            .map(String::trim)
            .filter { it.startsWith("{") }
            .mapNotNull { line -> runCatching { JSONObject(line) }.getOrNull() }

    /** restic's own last word on why it stopped, if it said one. */
    public fun exitError(): String? =
        messages()
            .lastOrNull { it.optString("message_type") == "exit_error" }
            ?.optString("message")
            ?.trim()
            ?.ifEmpty { null }

    public fun humanError(): String {
        exitError()?.let { return it }

        val fromStderr = stderr.lineSequence()
            .map(String::trim)
            .lastOrNull { it.isNotEmpty() && !it.startsWith("{") }
        if (!fromStderr.isNullOrEmpty()) return fromStderr

        return ResticExit.describe(exitCode)
    }

    public fun itemErrors(): List<ResticItemError> =
        messages()
            .filter { it.optString("message_type") == "error" }
            .map { o ->
                ResticItemError(
                    item = o.optString("item").trim(),
                    message = (o.optJSONObject("error")?.optString("message") ?: o.optString("error")).trim(),
                )
            }
            .toList()
}

public data class ResticItemError(
    public val item: String,
    public val message: String,
) {
    public val syscall: String get() = message.substringBefore(' ').trimEnd(':')

    override fun toString(): String =
        listOf(item, message).filter { it.isNotEmpty() }.joinToString(": ")
}

public class ResticException(
    message: String,
    cause: Throwable? = null,
    public val exitCode: Int? = null,
) : Exception(message, cause)
