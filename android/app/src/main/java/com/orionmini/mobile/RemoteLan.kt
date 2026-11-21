// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.content.Context
import kotlinx.serialization.json.*
import okhttp3.*
import java.security.MessageDigest
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import java.util.Base64
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLContext
import javax.net.ssl.X509TrustManager
import sefirah.network.orion.OrionRemote
import sefirah.network.orion.RemoteResult

/**
 * Phone remote over the local network. Saiph Cloud's mailbox is polled, so a swipe took seconds
 * to move the pointer. When this phone and a computer share a private network the phone asks
 * for a direct channel (`remote.lan.request`); the computer answers with a one-use invitation
 * (`remote.lan`) sealed for this phone, and the touchpad and keyboard then use a pinned-TLS
 * socket ([ScreenSender]'s design). The desktop's `remote_lan.py` is the other half. Nothing
 * here is logged, and the invitation's secret never leaves memory. Without a channel the
 * commands keep using the mailbox.
 */
internal object RemoteLan {
    const val REQUEST = "remote.lan.request"
    const val OFFER = "remote.lan"
    private const val ASK_AGAIN_MS = 6000L
    private val KEYS = setOf("session", "addresses", "port", "certificate", "secret", "expires")
    private val links = ConcurrentHashMap<String, Link>()
    private val asked = ConcurrentHashMap<String, Long>()
    private val beat = Executors.newSingleThreadScheduledExecutor { Thread(it, "orion-remote-lan").apply { isDaemon = true } }

    fun live(computer: String) = links[computer]?.ready == true

    /** True when the socket still holds unsent text; touchpad movement then waits and merges. */
    fun busy(computer: String) = links[computer]?.let { it.ready && it.queued() > 0 } == true

    /** Ask [computer] for a direct channel unless one is open or was just asked for. */
    fun ask(context: Context, computer: String) {
        if (live(computer)) return
        val now = System.currentTimeMillis()
        if (now - (asked[computer] ?: 0L) < ASK_AGAIN_MS) return
        asked[computer] = now
        HostedRuntime.get(context).enqueueRemote(computer, buildJsonObject { put("type", REQUEST) })
    }

    /** One remote command (no "type") to [computer] over its open channel; false when there is none. */
    fun send(computer: String, command: JsonObject): Boolean {
        val link = links[computer] ?: return false
        return link.send(buildJsonObject { put("t", "cmd"); put("c", command) }.toString())
    }

    /** A computer's answer to [ask]: validated strictly, then connected in the background. */
    fun accept(computer: String, payload: JsonObject) {
        val offer = runCatching { Invitation.parse(payload) }.getOrNull() ?: return
        links.remove(computer)?.close()
        val link = Link(computer, offer)
        links[computer] = link
        link.connect()
    }

    fun closeAll() { links.values.forEach { it.close() }; links.clear(); asked.clear() }

    private class Invitation(val session: String, val addresses: List<String>, val port: Int, val certificate: String, val secret: String) {
        companion object {
            fun parse(payload: JsonObject): Invitation {
                val value = JsonObject(payload - "type")
                require(value.keys == KEYS)
                fun text(key: String) = value.getValue(key).jsonPrimitive.let { require(it.isString); it.content }
                fun number(key: String) = value.getValue(key).jsonPrimitive.let { require(!it.isString && it.booleanOrNull == null); it.content.toLong() }
                val session = text("session"); val certificate = text("certificate"); val secret = text("secret")
                require(Regex("[a-f0-9]{32}").matches(session) && Regex("[a-f0-9]{64}").matches(certificate))
                require(Regex("[A-Za-z0-9_-]{43}").matches(secret) && Base64.getUrlDecoder().decode(secret).size == 32)
                val addresses = value.getValue("addresses").jsonArray.map { it.jsonPrimitive.let { item -> require(item.isString); item.content } }
                require(addresses.size in 1..8 && addresses.distinct().size == addresses.size && addresses.all(CameraOffer::localAddress))
                val port = number("port"); val expires = number("expires"); val now = System.currentTimeMillis() / 1000
                require(port in 1024..65535 && expires > now && expires <= now + SessionOffer.MAX_LIFETIME)
                return Invitation(session, addresses, port.toInt(), certificate, secret)
            }
        }
    }

    private class Link(val computer: String, val offer: Invitation) {
        @Volatile var ready = false
        @Volatile private var closed = false
        private var socket: WebSocket? = null
        private var heartbeat: ScheduledFuture<*>? = null
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
        private val client = OkHttpClient.Builder().sslSocketFactory(tls.socketFactory, trust).proxy(java.net.Proxy.NO_PROXY)
            .connectionSpecs(listOf(ConnectionSpec.MODERN_TLS)).connectTimeout(2, TimeUnit.SECONDS)
            .readTimeout(0, TimeUnit.SECONDS).writeTimeout(3, TimeUnit.SECONDS).pingInterval(3, TimeUnit.SECONDS)
            .retryOnConnectionFailure(false).followRedirects(false).build()

        fun queued() = socket?.queueSize() ?: 0L

        /** Each address twice: a failed handshake never claims the one-use invitation. */
        fun connect(index: Int = 0, retried: Boolean = false) {
            if (closed) return
            if (index >= offer.addresses.size) { end(); return }
            val url = "wss://${offer.addresses[index]}:${offer.port}/remote/${offer.session}"
            socket = client.newWebSocket(Request.Builder().url(url).header("Authorization", "Bearer ${offer.secret}").build(),
                object : WebSocketListener() {
                    override fun onOpen(webSocket: WebSocket, response: Response) {
                        if (closed) { webSocket.cancel(); return }
                        ready = true
                        heartbeat = beat.scheduleWithFixedDelay({ if (ready) socket?.send("""{"t":"hb"}""") }, 4, 4, TimeUnit.SECONDS)
                    }
                    override fun onFailure(webSocket: WebSocket, failure: Throwable, response: Response?) {
                        response?.close()
                        if (closed) return
                        if (ready || response != null) end() else if (!retried) connect(index, true) else connect(index + 1)
                    }
                    override fun onClosing(webSocket: WebSocket, code: Int, reason: String) { webSocket.close(1000, null); end() }
                    override fun onClosed(webSocket: WebSocket, code: Int, reason: String) { end() }
                    override fun onMessage(webSocket: WebSocket, bytes: okio.ByteString) { end() }
                    override fun onMessage(webSocket: WebSocket, text: String) {
                        val result = runCatching { result(text) }.getOrNull()
                        if (result == null) end() else OrionRemote.result.value = result
                    }
                })
        }

        private fun result(text: String): RemoteResult {
            require(text.length <= 1024)
            val value = Json.parseToJsonElement(text).jsonObject
            require(value.keys == setOf("t", "app", "control", "ok", "message") && value.getValue("t").jsonPrimitive.content == "result")
            fun field(key: String, limit: Int) = value.getValue(key).jsonPrimitive.let { require(it.isString && it.content.length <= limit); it.content }
            return RemoteResult(computer, field("app", 32), field("control", 32), value.getValue("ok").jsonPrimitive.boolean, field("message", 200))
        }

        fun send(text: String): Boolean = ready && socket?.send(text) == true

        fun end() { close(); if (links[computer] === this) links.remove(computer) }

        fun close() {
            closed = true; ready = false; heartbeat?.cancel(false); socket?.cancel(); socket = null
            client.dispatcher.executorService.shutdown(); client.connectionPool.evictAll()
        }
    }
}
