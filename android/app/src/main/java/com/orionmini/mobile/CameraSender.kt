// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import okhttp3.*
import okio.ByteString.Companion.toByteString
import java.nio.ByteBuffer
import java.security.MessageDigest
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLContext
import javax.net.ssl.X509TrustManager

/** Pinned TLS and one-use bearer authentication. At most one queued image. */
internal class CameraSender(private val offer: CameraOffer, private val connected: () -> Unit,
    private val ended: () -> Unit) {
    @Volatile private var closed = false
    @Volatile private var ready = false
    private var socket: WebSocket? = null
    private var sequence = 0L
    @Volatile internal var framesSent = 0L
        private set
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

    fun connect(index: Int = 0) {
        if (closed) return
        if (index >= offer.addresses.size || System.currentTimeMillis() / 1000 >= offer.expires) { ended(); return }
        val request = Request.Builder().url("wss://${offer.addresses[index]}:${offer.port}/camera/${offer.session}")
            .header("Authorization", "Bearer ${offer.secret}").build()
        socket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                if (closed) { webSocket.cancel(); return }
                ready = true; connected()
            }
            override fun onFailure(webSocket: WebSocket, failure: Throwable, response: Response?) {
                response?.close()
                if (!closed) { if (ready || response != null) ended() else connect(index + 1) }
            }
            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) { webSocket.close(1000, null); if (!closed) ended() }
            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) { if (!closed) ended() }
            override fun onMessage(webSocket: WebSocket, bytes: okio.ByteString) { close(); ended() }
            override fun onMessage(webSocket: WebSocket, text: String) { close(); ended() }
        })
    }
    @Synchronized fun frame(jpeg: ByteArray, width: Int, height: Int, rotation: Int) {
        val current = socket ?: return
        if (closed || !ready || current.queueSize() > 0 || jpeg.size !in 4..511982 || width !in 1..1280
            || height !in 1..1280 || width * height > 1280 * 720 || rotation !in listOf(0, 90, 180, 270)) return
        val value = ByteBuffer.allocate(18 + jpeg.size).put(byteArrayOf(83, 67, 70, 49)).putShort(width.toShort())
            .putShort(height.toShort()).putShort(rotation.toShort()).putLong(++sequence).put(jpeg).array()
        if (!current.send(value.toByteString())) ended() else framesSent++
    }
    fun close() {
        closed = true; ready = false; socket?.cancel(); socket = null
        client.dispatcher.executorService.shutdown(); client.connectionPool.evictAll()
    }
}
