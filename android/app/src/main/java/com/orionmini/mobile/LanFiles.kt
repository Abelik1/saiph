// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.async
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.json.*
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import okio.BufferedSink
import java.io.File
import java.io.IOException
import java.io.InputStream
import java.security.MessageDigest
import java.security.SecureRandom
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import java.util.Base64
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import javax.net.ssl.SSLContext
import javax.net.ssl.X509TrustManager

/**
 * A local file invitation (`orion-file:1:`), carried as the `invite` of a sealed
 * [SessionOffer] with service "file". The desktop's `session_offer.read_file_invite`
 * applies the same checks (docs/LAN_FILES.md). "get": the computer serves the file
 * to this phone. "put": the computer accepts this phone's upload for request [request].
 * Never put its secret in URLs, logs, saved state or intents.
 */
internal class FileOffer(val session: String, val addresses: List<String>, val port: Int, val certificate: String,
    val secret: String, val expires: Long, val mode: String, val name: String, val size: Long, val sha256: String,
    val request: String) {
    companion object {
        const val PREFIX = "orion-file:1:"
        private val KEYS = setOf("session", "addresses", "port", "certificate", "secret", "expires", "mode", "name", "size",
            "sha256", "request")

        fun parse(code: String, now: Long = System.currentTimeMillis() / 1000): FileOffer {
            require(code.length in 100..2048 && code.startsWith(PREFIX))
            val encoded = code.removePrefix(PREFIX)
            require(Regex("[A-Za-z0-9_-]+").matches(encoded))
            val value = Json.parseToJsonElement(Base64.getUrlDecoder().decode(encoded).toString(Charsets.UTF_8)).jsonObject
            require(value.keys == KEYS)
            fun text(key: String) = value.getValue(key).jsonPrimitive.let { require(it.isString); it.content }
            fun number(key: String) = LanFileFormat.integer(value.getValue(key))
            val session = text("session"); val certificate = text("certificate"); val secret = text("secret")
            require(Regex("[a-f0-9]{32}").matches(session) && Regex("[a-f0-9]{64}").matches(certificate))
            require(Regex("[A-Za-z0-9_-]{43}").matches(secret) && Base64.getUrlDecoder().decode(secret).size == 32)
            val addresses = value.getValue("addresses").jsonArray.map { it.jsonPrimitive.let { item -> require(item.isString); item.content } }
            require(addresses.size in 1..8 && addresses.distinct().size == addresses.size && addresses.all(CameraOffer::localAddress))
            val port = number("port"); val expires = number("expires")
            require(port in 1024..65535 && expires > now && expires <= now + SessionOffer.MAX_LIFETIME)
            val mode = text("mode"); val name = text("name"); val size = number("size"); val sha256 = text("sha256"); val request = text("request")
            require(mode in setOf("get", "put") && LanFileFormat.validName(name) && size in 0..LanFileFormat.MAX_BYTES)
            require(Regex("[a-f0-9]{64}").matches(sha256))
            require(if (mode == "get") request.isEmpty() else Regex("[a-f0-9]{32}").matches(request))
            return FileOffer(session, addresses, port.toInt(), certificate, secret, expires, mode, name, size, sha256, request)
        }
    }
}

/** The phone's upload request and a receiver's refusal; desktop `session_offer.py` has the same rules. */
internal object LanFileFormat {
    const val REQUEST = "file.lan.request"
    const val REFUSE = "session.refuse"
    const val MAX_BYTES = 1L shl 40
    val REASONS = setOf("unreachable", "storage", "busy")
    private val RESERVED = setOf("CON", "PRN", "AUX", "NUL") + (1..9).flatMap { listOf("COM$it", "LPT$it") }

    /** This phone has a private IPv4 address (Wi-Fi or Ethernet), so a direct transfer may work. */
    fun onPrivateNetwork(): Boolean = runCatching {
        java.net.NetworkInterface.getNetworkInterfaces().toList().any { network ->
            network.isUp && !network.isLoopback && network.inetAddresses.toList().any {
                it is java.net.Inet4Address && CameraOffer.localAddress(it.hostAddress.orEmpty())
            }
        }
    }.getOrDefault(false)

    fun integer(value: JsonElement?): Long {
        val primitive = value as? JsonPrimitive ?: throw IllegalArgumentException()
        require(!primitive.isString && primitive.booleanOrNull == null)
        return primitive.content.toLong()
    }
    private fun text(value: JsonElement?): String {
        val primitive = value as? JsonPrimitive ?: throw IllegalArgumentException()
        require(primitive.isString)
        return primitive.content
    }

    /** At most 255 UTF-8 bytes, no path, control character or reserved Windows name: both platforms create it as is. */
    fun validName(name: String): Boolean {
        if (name.isEmpty() || name == "." || name == ".." || name.last() == ' ' || name.last() == '.') return false
        var index = 0
        while (index < name.length) {
            val point = name.codePointAt(index)
            if (point < 32 || point in 0xD800..0xDFFF || "/\\:*?\"<>|".indexOf(point.toChar()) >= 0 && point < 128) return false
            index += Character.charCount(point)
        }
        return name.toByteArray(Charsets.UTF_8).size <= 255 && name.substringBefore('.').uppercase(java.util.Locale.ROOT) !in RESERVED
    }

    /** A name both platforms accept, from whatever the sharing app called the file. */
    fun safeName(name: String): String {
        var value = buildString {
            var index = 0
            while (index < name.length) {
                val point = name.codePointAt(index)
                if (point < 32 || point in 0xD800..0xDFFF || point < 128 && "/\\:*?\"<>|".indexOf(point.toChar()) >= 0) append('_')
                else appendCodePoint(point)
                index += Character.charCount(point)
            }
        }.trim().trimEnd('.', ' ')
        while (value.toByteArray(Charsets.UTF_8).size > 255) value = value.dropLast(1).trimEnd('.', ' ')
        return if (validName(value)) value else "shared-file"
    }

    fun request(name: String, size: Long, sha256: String, now: Long = System.currentTimeMillis() / 1000): JsonObject {
        val id = ByteArray(16).also(SecureRandom()::nextBytes).joinToString("") { "%02x".format(it) }
        return buildJsonObject {
            put("type", REQUEST); put("version", 1); put("id", id); put("name", name); put("size", size); put("sha256", sha256)
            // Under the 120 s maximum, so a computer whose clock is a little behind still accepts it.
            put("expires_at", now + 100)
        }.also { checkNotNull(parseRequest(it, now)) }
    }

    fun parseRequest(payload: JsonObject, now: Long = System.currentTimeMillis() / 1000): JsonObject? = runCatching {
        require(payload.keys == setOf("type", "version", "id", "name", "size", "sha256", "expires_at"))
        require(text(payload["type"]) == REQUEST && integer(payload["version"]) == 1L)
        require(Regex("[a-f0-9]{32}").matches(text(payload["id"])) && validName(text(payload["name"])))
        require(integer(payload["size"]) in 0..MAX_BYTES && Regex("[a-f0-9]{64}").matches(text(payload["sha256"])))
        val expires = integer(payload["expires_at"])
        require(expires > now && expires <= now + SessionOffer.MAX_LIFETIME)
        payload
    }.getOrNull()

    fun refuse(id: String, reason: String) = buildJsonObject { put("type", REFUSE); put("version", 1); put("id", id); put("reason", reason) }
        .also { checkNotNull(parseRefuse(it)) }

    /** (offer or request ID, reason) of an exact refusal, or null. */
    fun parseRefuse(payload: JsonObject): Pair<String, String>? = runCatching {
        require(payload.keys == setOf("type", "version", "id", "reason"))
        require(text(payload["type"]) == REFUSE && integer(payload["version"]) == 1L)
        val id = text(payload["id"]); val reason = text(payload["reason"])
        require(Regex("[a-f0-9]{32}").matches(id) && reason in REASONS)
        id to reason
    }.getOrNull()
}

/** A transfer stopped after it started: [code] is the desktop's (lost, mismatch, refused, cancelled). */
internal class LanFailure(val code: String) : IOException(code)

/** Pinned TLS to one computer's file listener; the bearer secret is spent by [claim]. */
internal class LanFileClient(private val offer: FileOffer) {
    companion object {
        const val RESUME_MILLIS = 90_000L
        const val RETRY_MILLIS = 2_000L
        private const val CHUNK = 1 shl 16
    }
    private val trust = object : X509TrustManager {
        override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
        override fun checkClientTrusted(chain: Array<X509Certificate>, type: String) { throw CertificateException() }
        override fun checkServerTrusted(chain: Array<X509Certificate>, type: String) {
            if (chain.size != 1) throw CertificateException()
            chain[0].checkValidity()
            val actual = MessageDigest.getInstance("SHA-256").digest(chain[0].encoded)
            val expected = offer.certificate.chunked(2).map { it.toInt(16).toByte() }.toByteArray()
            if (!MessageDigest.isEqual(actual, expected)) throw CertificateException()
        }
    }
    private val tls = SSLContext.getInstance("TLS").apply { init(null, arrayOf(trust), null) }
    private val client = OkHttpClient.Builder().sslSocketFactory(tls.socketFactory, trust).hostnameVerifier { _, _ -> true }
        .proxy(java.net.Proxy.NO_PROXY).connectionSpecs(listOf(ConnectionSpec.MODERN_TLS))
        .connectTimeout(4, TimeUnit.SECONDS).readTimeout(15, TimeUnit.SECONDS).writeTimeout(15, TimeUnit.SECONDS)
        .retryOnConnectionFailure(false).followRedirects(false).build()
    private var address = offer.addresses.first()
    private var resume = ""

    private fun url(path: String) = "https://$address:${offer.port}/file/${offer.session}$path"
    private fun authorized(path: String) = Request.Builder().url(url(path)).header("Authorization", "Resume $resume")

    /** True once this phone holds the transfer; false when no address answered with the pinned certificate. */
    fun claim(cancelled: () -> Boolean = { false }): Boolean {
        for (candidate in offer.addresses) {
            if (cancelled()) return false
            address = candidate
            val request = Request.Builder().url(url("/claim")).header("Authorization", "Bearer ${offer.secret}")
                .post(ByteArray(0).toRequestBody(null)).build()
            try {
                client.newCall(request).execute().use { response ->
                    if (response.code != 200) return false  // Reached, but refused: spent or expired.
                    val value = Json.parseToJsonElement(response.body!!.string().take(512)).jsonObject
                    val token = value.getValue("resume").jsonPrimitive.content
                    require(Regex("[A-Za-z0-9_-]{43}").matches(token))
                    resume = token
                    return true
                }
            } catch (_: IOException) { continue } catch (_: IllegalArgumentException) { return false }
        }
        return false
    }

    /** "get": download into [destination] with resume; true when the computer's SHA-256 matched. */
    fun download(destination: File, progress: (Long) -> Unit, cancelled: () -> Boolean) {
        val digest = MessageDigest.getInstance("SHA-256")
        var received = 0L
        var last = System.currentTimeMillis()
        destination.outputStream().use { output ->
            progress(0)
            while (received < offer.size) {
                if (cancelled()) throw LanFailure("cancelled")
                if (System.currentTimeMillis() - last > RESUME_MILLIS) throw LanFailure("lost")
                try {
                    client.newCall(authorized("").header("Range", "bytes=$received-").get().build()).execute().use { response ->
                        if (response.code in setOf(403, 410, 416)) throw LanFailure("refused")
                        if (response.code != 206) throw IOException()
                        val input = response.body!!.byteStream(); val buffer = ByteArray(CHUNK)
                        while (received < offer.size) {
                            if (cancelled()) throw LanFailure("cancelled")
                            val count = input.read(buffer, 0, minOf(buffer.size.toLong(), offer.size - received).toInt())
                            if (count < 0) break
                            output.write(buffer, 0, count); digest.update(buffer, 0, count)
                            received += count; last = System.currentTimeMillis(); progress(received)
                        }
                    }
                } catch (failure: LanFailure) { throw failure } catch (_: IOException) {
                    if (received < offer.size) Thread.sleep(RETRY_MILLIS)
                }
            }
            output.flush(); output.fd.sync()
        }
        val hex = digest.digest().joinToString("") { "%02x".format(it) }
        // The computer reports "Sent" only after this phone's own result matches.
        val body = buildJsonObject { put("size", received); put("sha256", hex) }.toString().toByteArray()
        repeat(5) {
            try {
                client.newCall(authorized("/done").post(body.toRequestBody("application/json".toMediaType())).build()).execute().close()
                if (hex != offer.sha256) throw LanFailure("mismatch")
                return
            } catch (failure: LanFailure) { throw failure } catch (_: IOException) { Thread.sleep(1000) }
        }
        if (hex != offer.sha256) throw LanFailure("mismatch")
    }

    /** "put": upload [open]'s bytes with resume; returns once the computer verified size and SHA-256. */
    fun upload(open: () -> InputStream, progress: (Long) -> Unit, cancelled: () -> Boolean) {
        var last = System.currentTimeMillis()
        var sent = 0L
        progress(0)
        while (true) {
            if (cancelled()) throw LanFailure("cancelled")
            if (System.currentTimeMillis() - last > RESUME_MILLIS) throw LanFailure("lost")
            try {
                val offset = client.newCall(authorized("/received").get().build()).execute().use { response ->
                    if (response.code == 403) throw LanFailure("refused")
                    if (response.code != 200) throw IOException()
                    LanFileFormat.integer(Json.parseToJsonElement(response.body!!.string().take(512)).jsonObject["received"])
                }
                require(offset in 0..offer.size)
                if (offset > sent) last = System.currentTimeMillis()
                sent = offset; progress(sent)
                val body = object : RequestBody() {
                    override fun contentType() = "application/octet-stream".toMediaType()
                    override fun contentLength() = offer.size - offset
                    override fun writeTo(sink: BufferedSink) {
                        open().use { input ->
                            var skip = offset
                            while (skip > 0) { val skipped = input.skip(skip); if (skipped <= 0) throw IOException(); skip -= skipped }
                            val buffer = ByteArray(CHUNK); var left = offer.size - offset
                            while (left > 0) {
                                if (cancelled()) throw IOException("cancelled")
                                val count = input.read(buffer, 0, minOf(buffer.size.toLong(), left).toInt())
                                if (count < 0) throw LanFailure("changed")
                                sink.write(buffer, 0, count); left -= count; sent += count
                                last = System.currentTimeMillis(); progress(sent)
                            }
                        }
                    }
                }
                client.newCall(authorized("?offset=$offset").put(body).build()).execute().use { response ->
                    when (response.code) {
                        200 -> return
                        422 -> throw LanFailure("mismatch")
                        403 -> throw LanFailure("refused")
                        else -> throw IOException()
                    }
                }
            } catch (failure: LanFailure) { throw failure } catch (_: IOException) {
                Thread.sleep(RETRY_MILLIS)
            } catch (_: IllegalArgumentException) { throw LanFailure("refused") }
        }
    }

    fun close() { client.dispatcher.executorService.shutdown(); client.connectionPool.evictAll() }
}

/**
 * Files moving directly between this phone and a computer on the same private network.
 * Incoming files are fetched at once into private storage and wait for the owner's
 * Save; an upload waits for the computer's invitation, then streams with resume.
 * Memory only: a restarted process forgets unsaved files, and [clearStaged] removes them.
 */
internal class LanTransfers(private val folder: File, private val post: (String, JsonObject) -> Unit) {
    class Incoming(val id: String, val source: String, val computer: String, val name: String, val size: Long, val file: File) {
        @Volatile var state = "waiting"
        @Volatile var received = 0L
        @Volatile var error = ""
        val cancel = AtomicBoolean()
    }
    class Sending(val name: String, val computer: String, val size: Long) {
        @Volatile var sent = 0L
        @Volatile var connecting = true
    }
    sealed class Outcome {
        object Sent : Outcome()
        object Unreachable : Outcome()
        class Refused(val reason: String) : Outcome()
        class Failed(val code: String) : Outcome()
    }
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    val incoming = ConcurrentHashMap<String, Incoming>()
    private val waiting = ConcurrentHashMap<String, Pair<String, CompletableDeferred<Any>>>()
    @Volatile var sending: Sending? = null
        private set

    init { clearStaged() }
    fun clearStaged() { folder.listFiles()?.filter { it.name.endsWith(".saiph-part") }?.forEach { it.delete() } }

    /** A computer offers a file ("get"): fetch it now. Refusals let the computer fall back at once. */
    fun receive(offer: SessionOffer, source: String, computer: String) {
        val file = offer.file
        if (incoming.containsKey(offer.id)) return
        if (incoming.values.count { it.state in setOf("waiting", "receiving") } >= 4) { post(source, LanFileFormat.refuse(offer.id, "busy")); return }
        check(folder.isDirectory || folder.mkdirs())
        val item = Incoming(offer.id, source, computer, file.name, file.size, File(folder, java.util.UUID.randomUUID().toString() + ".saiph-part"))
        incoming[offer.id] = item
        if (folder.usableSpace < file.size + 64L * 1024 * 1024) {
            item.state = "failed"; item.error = "Not enough free space for ${file.name} (${HostedTransferText.megabytes(file.size, up = true)} MB)."
            post(source, LanFileFormat.refuse(offer.id, "storage")); return
        }
        scope.launch {
            val client = LanFileClient(file)
            try {
                if (!client.claim { item.cancel.get() }) {
                    incoming.remove(offer.id); item.file.delete()
                    if (!item.cancel.get()) post(source, LanFileFormat.refuse(offer.id, "unreachable"))
                    return@launch
                }
                item.state = "receiving"
                client.download(item.file, { item.received = it }, { item.cancel.get() })
                item.received = item.size; item.state = "ready"
            } catch (failure: Exception) {
                item.file.delete(); item.state = "failed"
                item.error = when ((failure as? LanFailure)?.code) {
                    "mismatch" -> "${item.name} arrived damaged and was deleted. Send it again."
                    "lost" -> "The connection to ${item.computer} was lost. Send it again on the same Wi-Fi."
                    "cancelled" -> "Receiving ${item.name} was stopped."
                    else -> "${item.name} could not be received from ${item.computer}."
                }
            } finally { client.close() }
        }
    }

    /** The computer withdrew its offer before this phone connected (it fell back to Saiph Cloud). */
    fun closed(id: String, source: String) {
        val item = incoming[id] ?: return
        if (item.source == source && item.state == "waiting") { item.cancel.set(true); incoming.remove(id) }
    }

    /** A "put" offer or a refusal for this phone's own request, from the computer it asked. */
    fun answered(request: String, source: String, answer: Any) {
        val (target, deferred) = waiting[request] ?: return
        if (target == source) deferred.complete(answer)
    }

    /**
     * Send one file directly. Hashes it, asks [target] for an upload invitation and streams it.
     * Runs in this object's own scope, so leaving the screen does not stop it.
     */
    suspend fun send(target: String, computer: String, name: String, size: Long, open: () -> InputStream): Outcome =
        scope.async { upload(target, computer, name, size, open) }.await()

    private suspend fun upload(target: String, computer: String, name: String, size: Long, open: () -> InputStream): Outcome {
        val progress = Sending(name, computer, size)
        sending = progress
        try {
            val digest = MessageDigest.getInstance("SHA-256"); var count = 0L
            open().use { input ->
                val buffer = ByteArray(1 shl 16)
                while (true) { val read = input.read(buffer); if (read < 0) break; digest.update(buffer, 0, read); count += read }
            }
            if (count != size) return Outcome.Failed("changed")
            val hex = digest.digest().joinToString("") { "%02x".format(it) }
            val request = LanFileFormat.request(name, size, hex)
            val id = request.getValue("id").jsonPrimitive.content
            val answer = CompletableDeferred<Any>()
            waiting[id] = target to answer
            try {
                post(target, request)
                // An older computer never answers: Saiph Cloud takes over after this wait.
                val reply = withTimeoutOrNull(45_000) { answer.await() } ?: return Outcome.Unreachable
                if (reply is String) return if (reply == "unreachable") Outcome.Unreachable else Outcome.Refused(reply)
                val offer = (reply as SessionOffer).file
                if (offer.mode != "put" || offer.request != id || offer.size != size || offer.name != name || offer.sha256 != hex)
                    return Outcome.Unreachable
                val client = LanFileClient(offer)
                try {
                    if (!client.claim()) { post(target, SessionOffer.closePayload(reply.id)); return Outcome.Unreachable }
                    progress.connecting = false
                    client.upload(open, { progress.sent = it }, { false })
                    return Outcome.Sent
                } catch (failure: LanFailure) {
                    return Outcome.Failed(failure.code)
                } finally { client.close() }
            } finally { waiting.remove(id) }
        } finally { if (sending === progress) sending = null }
    }

    /** Hand a verified file to [write] once, then forget it. */
    fun deliver(id: String, write: (File, String) -> Unit) {
        val item = incoming[id]
        check(item != null && item.state == "ready") { "This file is no longer available." }
        write(item.file, item.name)
        incoming.remove(id); item.file.delete()
    }

    fun dismiss(id: String) {
        val item = incoming.remove(id) ?: return
        item.cancel.set(true); item.file.delete()
    }

    /** Sign-out, sync off or a revoked computer: stop and remove everything. */
    fun clear(keep: Set<String>? = null) {
        for (item in incoming.values.toList()) if (keep == null || item.source !in keep) dismiss(item.id)
        if (keep == null) waiting.values.forEach { it.second.complete("unreachable") }
    }
}
