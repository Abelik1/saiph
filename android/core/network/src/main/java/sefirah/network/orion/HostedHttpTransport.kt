package sefirah.network.orion

import kotlinx.serialization.json.*
import okhttp3.CookieJar
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.net.URI
import java.net.Proxy
import java.security.Signature
import java.util.Base64
import java.util.UUID
import java.util.concurrent.TimeUnit

/** Isolated blocking HTTPS adapter; call on a worker, never from the UI thread. */
class HostedHttpTransport private constructor(
    private val origin: String,
    private val session: HostedSession,
    private val sender: Sender,
    private val clock: () -> Long,
) {
    internal fun interface Sender { fun send(request: Request, maximum: Int): ByteArray }

    companion object {
        fun create(origin: String, session: HostedSession): HostedHttpTransport = HostedSession.guarded {
            val normalized = checkedOrigin(origin)
            val client = OkHttpClient.Builder().followRedirects(false).followSslRedirects(false)
                .retryOnConnectionFailure(false).cookieJar(CookieJar.NO_COOKIES)
                .proxy(Proxy.NO_PROXY)
                .connectTimeout(10, TimeUnit.SECONDS).readTimeout(15, TimeUnit.SECONDS).callTimeout(20, TimeUnit.SECONDS).build()
            HostedHttpTransport(normalized, session, Sender { request, maximum ->
                client.newCall(request).execute().use { response ->
                    check(response.code in 200..299)
                    val body = response.body ?: throw HostedSessionException()
                    check(body.contentLength() <= maximum)
                    body.byteStream().use { input ->
                        val output = java.io.ByteArrayOutputStream()
                        val buffer = ByteArray(4096)
                        while (true) {
                            val count = input.read(buffer)
                            if (count < 0) break
                            check(output.size() + count <= maximum)
                            output.write(buffer, 0, count)
                        }
                        output.toByteArray()
                    }
                }
            }, { System.currentTimeMillis() / 1000 })
        }

        internal fun checkedOrigin(value: String): String {
            check(value.none { it.code <= 32 } && value.length <= 2048)
            val uri = URI(value)
            check(uri.scheme == "https" && !uri.host.isNullOrBlank() && uri.rawUserInfo == null &&
                uri.rawQuery == null && uri.rawFragment == null && uri.rawPath in listOf("", "/") && uri.port in -1..65535 && uri.port != 0)
            return value.trimEnd('/')
        }

        internal fun forTests(origin: String, session: HostedSession, sender: Sender, clock: () -> Long): HostedHttpTransport =
            HostedHttpTransport(checkedOrigin(origin), session, sender, clock)

        internal fun parse(raw: ByteArray): JsonObject {
            // Bound nesting before invoking a recursive JSON parser. Hosted
            // metadata contains ASCII IDs, keys and ciphertext only.
            var quoted = false
            var escaped = false
            var depth = 0
            for (byte in raw) {
                val value = byte.toInt()
                check(value in 0..127)
                if (quoted) {
                    if (escaped) escaped = false else when (value) { 92 -> escaped = true; 34 -> quoted = false }
                } else when (value) { 34 -> quoted = true; 91, 123 -> check(++depth <= 24); 93, 125 -> check(--depth >= 0) }
            }
            check(depth == 0 && !quoted)
            val source = String(raw, Charsets.US_ASCII)
            var position = 0
            var nodes = 200_000
            fun whitespace() { while (position < source.length && source[position] in " \t\r\n") position++ }
            fun string(): String {
                check(position < source.length && source[position] == '"')
                val start = position++
                var escaped = false
                while (position < source.length) {
                    val c = source[position++]
                    if (escaped) escaped = false else if (c == '\\') escaped = true else if (c == '"') {
                        return Json.parseToJsonElement(source.substring(start, position)).jsonPrimitive.content
                    }
                }
                error("Invalid JSON")
            }
            fun visit(depth: Int) {
                whitespace()
                check(--nodes >= 0 && depth <= 24 && position < source.length)
                when (source[position]) {
                    '{' -> {
                        position++; whitespace()
                        val keys = mutableSetOf<String>()
                        if (position < source.length && source[position] == '}') position++ else while (true) {
                            whitespace(); check(keys.add(string())); whitespace()
                            check(position < source.length && source[position++] == ':')
                            visit(depth + 1); whitespace(); check(position < source.length)
                            val separator = source[position++]
                            if (separator == '}') break
                            check(separator == ',')
                        }
                    }
                    '[' -> {
                        position++; whitespace()
                        if (position < source.length && source[position] == ']') position++ else while (true) {
                            visit(depth + 1); whitespace(); check(position < source.length)
                            val separator = source[position++]
                            if (separator == ']') break
                            check(separator == ',')
                        }
                    }
                    '"' -> string()
                    else -> {
                        val start = position
                        while (position < source.length && source[position] !in ",]} \t\r\n") position++
                        check(position > start)
                    }
                }
            }
            visit(0); whitespace(); check(position == source.length)
            return Json.parseToJsonElement(source).jsonObject
        }
    }

    private fun call(method: String, path: String, body: JsonObject? = null, token: String? = null, maximum: Int = 100_000): JsonObject = HostedSession.guarded {
        val raw = if (body == null) ByteArray(0) else HostedEnvelope.canonical(body)
        check(raw.size <= 65_536)
        val request = Request.Builder().url(origin + path).header("Accept", "application/json").header("User-Agent", "Orion-hosted-Android-development")
        if (token != null) {
            check(token.isNotEmpty() && token.length <= 16_384 && token.none { it.code <= 32 || it.code >= 127 })
            request.header("Authorization", "Bearer $token")
        } else {
            session.currentMembers()
            val timestamp = clock().toString()
            val nonce = UUID.randomUUID().toString()
            val wire = "$method\n$path\n$timestamp\n$nonce\n${HostedSession.digest(raw)}".toByteArray(Charsets.US_ASCII)
            val proof = Signature.getInstance("SHA256withECDSA").run { initSign(session.keys.signingPrivate); update(wire); sign() }
            request.header("X-Orion-Device-Id", session.deviceId).header("X-Orion-Timestamp", timestamp)
                .header("X-Orion-Nonce", nonce).header("X-Orion-Signature", Base64.getEncoder().encodeToString(proof))
        }
        request.method(method, if (method == "POST") raw.toRequestBody("application/json".toMediaType()) else null)
        val response = sender.send(request.build(), maximum)
        check(response.size <= maximum)
        parse(response)
    }

    fun publishEnvelope(envelope: JsonObject): JsonObject = call("POST", "/v1/sealed/events", envelope)
    fun allocateBlob(descriptor: JsonObject): JsonObject = call("POST", "/v1/sealed/blobs", descriptor)
    fun uploadChunk(id: String, index: Int, data: ByteArray): JsonObject = HostedSession.guarded {
        check(UUID.fromString(id).toString() == id && index in 0..639 && data.size in 1..32768)
        call("POST", "/v1/sealed/blobs/$id/chunks/$index", buildJsonObject { put("data", Base64.getEncoder().encodeToString(data)) })
    }
    fun completeBlob(id: String): JsonObject = HostedSession.guarded {
        check(UUID.fromString(id).toString() == id)
        call("POST", "/v1/sealed/blobs/$id/complete", buildJsonObject {})
    }
    fun downloadChunk(id: String, index: Int): ByteArray = HostedSession.guarded {
        check(UUID.fromString(id).toString() == id && index in 0..639)
        val result = call("GET", "/v1/sealed/blobs/$id/chunks/$index")
        check(result.keys == setOf("data"))
        val encoded = HostedSession.text(result["data"])
        check(encoded.length <= 43692)
        val raw = Base64.getDecoder().decode(encoded)
        check(raw.size in 1..32768 && Base64.getEncoder().encodeToString(raw) == encoded)
        raw
    }

    /** This account's Cloud access (free trial end, grant kinds); readable without a grant. */
    fun access(accessToken: String): JsonObject = call("GET", "/v1/access", token = accessToken, maximum = 4096)
    fun submitEnrollment(accessToken: String): JsonObject = call("POST", "/v1/devices/requests", session.enrollment(), accessToken)

    /** Hands this phone's signed request to the service so the computer can show it without pasting. */
    fun offerRequest(accessToken: String, code: String): JsonObject =
        call("POST", "/v1/devices/approval-requests", buildJsonObject { put("code", code) }, accessToken)

    fun refreshTrust(accessToken: String, maximumPages: Int = 64) {
        session.invalidate()
        try {
            check(maximumPages in 1..64)
            repeat(maximumPages) {
                val checkpoint = session.pagingCheckpoint()
                val suffix = if (checkpoint.version == 0L) "" else "&after_hash=${checkpoint.digest}"
                val response = call("GET", "/v1/devices/rosters/page?after_version=${checkpoint.version}&limit=16$suffix",
                    token = accessToken, maximum = 1_000_000)
                check(response.keys == setOf("chain", "more"))
                val more = response.getValue("more")
                check(more == JsonPrimitive(true) || more == JsonPrimitive(false))
                val continued = more == JsonPrimitive(true)
                session.acceptPage(response.getValue("chain").jsonArray, final = !continued)
                if (!continued) return
            }
            // Bounded work per call. Verified historical progress remains
            // durable; the caller may explicitly resume another refresh.
            throw HostedSessionException()
        } catch (_: Exception) { session.invalidate(); throw HostedSessionException() }
    }

    fun send(target: String, payload: JsonObject): JsonObject = HostedSession.guarded {
        val result = call("POST", "/v1/sealed/events", session.encrypt(target, payload))
        check(result["accepted"] == JsonPrimitive(true))
        result
    }

    /** Every remote ACK follows successful durable encrypted local acceptance. */
    fun pollIntoEncryptedInbox(): List<HostedInboxReceipt> = HostedSession.guarded {
        session.currentMembers()
        val response = call("GET", "/v1/sealed/events", maximum = 4_000_000)
        check(response.keys == setOf("events"))
        val events = response.getValue("events").jsonArray
        check(events.size <= 100)
        events.map {
            val receipt = session.receiveIntoEncryptedInbox(it.jsonObject)
            val result = call("DELETE", "/v1/sealed/events/${receipt.id}")
            check(result["ok"] == JsonPrimitive(true))
            receipt
        }
    }
}
