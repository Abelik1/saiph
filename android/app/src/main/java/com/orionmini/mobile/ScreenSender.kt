// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import okhttp3.*
import okio.ByteString.Companion.toByteString
import java.security.MessageDigest
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLContext
import javax.net.ssl.X509TrustManager

/**
 * The phone screen's socket: the camera's pinned TLS and one-use bearer authentication
 * ([CameraSender]), plus validated text requests from the computer. At most one queued frame.
 */
internal class ScreenSender(private val offer: ScreenOffer, private val connected: () -> Unit,
    private val request: (ScreenRequest) -> Unit, private val ended: () -> Unit) {
    @Volatile private var closed = false
    @Volatile private var ready = false
    private var socket: WebSocket? = null
    private var sequence = 0L
    fun canAcceptFrame(): Boolean = !closed && ready && socket?.queueSize() == 0L
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
        .connectionSpecs(listOf(ConnectionSpec.MODERN_TLS)).connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.SECONDS).writeTimeout(5, TimeUnit.SECONDS).pingInterval(3, TimeUnit.SECONDS)
        .retryOnConnectionFailure(false).followRedirects(false).build()

    /** Each address is tried twice: a failed handshake never claims the one-use invitation. */
    fun connect(index: Int = 0, retried: Boolean = false) {
        if (closed) return
        if (index >= offer.addresses.size || System.currentTimeMillis() / 1000 >= offer.expires) { ended(); return }
        val url = "wss://${offer.addresses[index]}:${offer.port}/screen/${offer.session}"
        socket = client.newWebSocket(Request.Builder().url(url).header("Authorization", "Bearer ${offer.secret}").build(),
            object : WebSocketListener() {
                override fun onOpen(webSocket: WebSocket, response: Response) {
                    if (closed) { webSocket.cancel(); return }
                    ready = true; connected()
                }
                override fun onFailure(webSocket: WebSocket, failure: Throwable, response: Response?) {
                    response?.close()
                    if (!closed) { if (ready || response != null) ended() else if (!retried) connect(index, true) else connect(index + 1) }
                }
                override fun onClosing(webSocket: WebSocket, code: Int, reason: String) { webSocket.close(1000, null); if (!closed) ended() }
                override fun onClosed(webSocket: WebSocket, code: Int, reason: String) { if (!closed) ended() }
                // The computer sends only exact text requests; anything else ends the session.
                override fun onMessage(webSocket: WebSocket, bytes: okio.ByteString) { close(); ended() }
                override fun onMessage(webSocket: WebSocket, text: String) {
                    val parsed = ScreenProtocol.request(text)
                    if (parsed == null) { close(); ended() } else if (!closed && ready) request(parsed)
                }
            })
    }

    @Synchronized fun frame(jpeg: ByteArray, width: Int, height: Int) {
        val current = socket ?: return
        if (closed || !ready || current.queueSize() > 0 || maxOf(width, height) > offer.maxSide || width * height > offer.maxPixels) return
        val value = runCatching { ScreenProtocol.frame(jpeg, width, height, ++sequence) }.getOrNull() ?: return
        if (!current.send(value.toByteString())) ended()
    }

    fun text(value: String) { if (!closed && ready && socket?.send(value) == false) ended() }

    fun close() {
        closed = true; ready = false; socket?.cancel(); socket = null
        client.dispatcher.executorService.shutdown(); client.connectionPool.evictAll()
    }
}
