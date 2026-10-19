// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import kotlinx.serialization.json.*
import java.io.Closeable
import java.io.InputStream
import java.math.BigInteger
import java.net.*
import java.security.*
import java.security.interfaces.ECPublicKey
import java.security.spec.*
import java.util.Base64
import javax.crypto.KeyAgreement
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/**
 * Find the main computer on this Wi-Fi and receive its signed root code without
 * a QR code. The phone half of the desktop's `lan_link.py`; both test suites read
 * `lan-link-vectors.json`.
 *
 * The phone commits to its ephemeral key and nonce before it sees the computer's,
 * so a man in the middle gets one guess per attempt at a matching six-digit code.
 * The phone pins the computer only after its owner confirms the same code is on
 * the computer's screen, and then sends its request authenticated under the
 * compared transcript. The computer still approves with native owner verification.
 * Discovery reveals no keys; only private IPv4 peers are contacted.
 */
internal object LanLink {
    const val VERSION = 1
    const val DISCOVERY_PORT = 47390
    private const val MAX_LINE = 8192
    class Computer(val name: String, val address: String, val port: Int)

    fun b64(value: ByteArray): String = Base64.getUrlEncoder().withoutPadding().encodeToString(value)
    fun unb64(value: String, size: Int): ByteArray {
        require(Regex("[A-Za-z0-9_-]+").matches(value))
        val raw = Base64.getUrlDecoder().decode(value)
        require(raw.size == size && b64(raw) == value)
        return raw
    }
    private fun ascii(value: String) = value.toByteArray(Charsets.US_ASCII)
    private fun framed(vararg parts: ByteArray): ByteArray = parts.fold(ByteArray(0)) { out, part ->
        out + byteArrayOf((part.size ushr 24).toByte(), (part.size ushr 16).toByte(), (part.size ushr 8).toByte(), part.size.toByte()) + part
    }
    private fun sha256(value: ByteArray): ByteArray = MessageDigest.getInstance("SHA-256").digest(value)
    fun hmac(key: ByteArray, value: ByteArray): ByteArray = Mac.getInstance("HmacSHA256").run { init(SecretKeySpec(key, "HmacSHA256")); doFinal(value) }

    fun commitment(key: ByteArray, nonce: ByteArray) = sha256(ascii("saiph-link-commit-v1\u0000") + framed(key, nonce))
    fun transcript(root: String, commit: ByteArray, phoneKey: ByteArray, computerKey: ByteArray, phoneNonce: ByteArray, computerNonce: ByteArray) =
        sha256(ascii("saiph-link-transcript-v1\u0000") + framed(ascii(root), commit, phoneKey, computerKey, phoneNonce, computerNonce))
    fun comparisonCode(digest: ByteArray): String {
        val value = BigInteger(1, sha256(ascii("saiph-link-code-v1\u0000") + digest).copyOf(8)).mod(BigInteger.valueOf(1_000_000)).toInt()
        return "%03d %03d".format(value / 1000, value % 1000)
    }
    /** HKDF-SHA256 (RFC 5869) with the transcript as salt; one 32-byte block. */
    fun macKey(shared: ByteArray, digest: ByteArray): ByteArray {
        val prk = hmac(digest, shared)
        return hmac(prk, ascii("saiph-link-mac-v1") + byteArrayOf(1))
    }
    fun requestMac(key: ByteArray, code: String) = hmac(key, ascii("saiph-link-request-v1\u0000") + ascii(code))
    fun receivedMac(key: ByteArray, code: String) = hmac(key, ascii("saiph-link-received-v1\u0000") + ascii(code))

    private val curve: ECParameterSpec by lazy {
        AlgorithmParameters.getInstance("EC").apply { init(ECGenParameterSpec("secp256r1")) }.getParameterSpec(ECParameterSpec::class.java)
    }
    fun publicBytes(key: ECPublicKey): ByteArray {
        fun fixed(value: BigInteger) = value.toByteArray().let { bytes -> ByteArray(32 - minOf(32, bytes.size)) + bytes.takeLast(32).toByteArray() }
        return byteArrayOf(4) + fixed(key.w.affineX) + fixed(key.w.affineY)
    }
    /** An uncompressed P-256 point that is verified to lie on the curve before any key agreement. */
    fun readPublic(raw: ByteArray): PublicKey {
        require(raw.size == 65 && raw[0] == 4.toByte())
        val x = BigInteger(1, raw.copyOfRange(1, 33)); val y = BigInteger(1, raw.copyOfRange(33, 65))
        val field = (curve.curve.field as ECFieldFp).p
        require(x < field && y < field)
        require(y.pow(2).mod(field) == x.pow(3).add(curve.curve.a.multiply(x)).add(curve.curve.b).mod(field))
        return KeyFactory.getInstance("EC").generatePublic(ECPublicKeySpec(ECPoint(x, y), curve))
    }
    fun privateKey(scalarHex: String): PrivateKey = KeyFactory.getInstance("EC").generatePrivate(ECPrivateKeySpec(BigInteger(scalarHex, 16), curve))
    fun agree(private: PrivateKey, peer: ByteArray): ByteArray = KeyAgreement.getInstance("ECDH").run { init(private); doPhase(readPublic(peer), true); generateSecret() }

    fun cleanName(value: String): String = value.filter { !it.isISOControl() }.trim().take(40).trim().ifEmpty { "Phone" }
    fun privateIpv4(value: String): Boolean = CameraOffer.localAddress(value) && value != "10.0.0.0" && value != "172.16.0.0" && value != "192.168.0.0"

    private fun line(value: JsonObject): ByteArray {
        val raw = (value.toString() + "\n").toByteArray(Charsets.UTF_8)
        require(raw.size <= MAX_LINE)
        return raw
    }
    private fun read(raw: String, type: String, keys: Set<String>): JsonObject {
        val value = Json.parseToJsonElement(raw).jsonObject
        require(value.keys == keys + "type" && value["type"] == JsonPrimitive(type))
        return value
    }
    private fun text(value: JsonObject, key: String): String = value.getValue(key).jsonPrimitive.let { require(it.isString); it.content }

    /** The phone's steps, independent of sockets so tests can drive them directly. */
    class Handshake(private val name: String, private val pair: KeyPair = KeyPairGenerator.getInstance("EC").apply { initialize(ECGenParameterSpec("secp256r1")) }.generateKeyPair(),
                    private val nonce: ByteArray = ByteArray(32).also { SecureRandom().nextBytes(it) }) {
        val publicKey = publicBytes(pair.public as ECPublicKey)
        val commit = commitment(publicKey, nonce)
        var rootCode = ""; private set
        var code = ""; private set
        private var key = ByteArray(0)
        fun hello(): ByteArray = line(buildJsonObject {
            put("type", "link.hello"); put("version", VERSION); put("commit", b64(commit)); put("name", cleanName(name))
        })
        /** Reads the computer's signed root code and answers with the reveal; [code] is then shown. */
        fun root(raw: String): ByteArray {
            val message = read(raw, "link.root", setOf("root_code", "ephemeral", "nonce"))
            val root = text(message, "root_code")
            require(root.length <= 4096 && root.all { it.code in 32..126 })
            val computerKey = unb64(text(message, "ephemeral"), 65); val computerNonce = unb64(text(message, "nonce"), 32)
            val digest = transcript(root, commit, publicKey, computerKey, nonce, computerNonce)
            key = macKey(agree(pair.private, computerKey), digest)
            rootCode = root; code = comparisonCode(digest)
            return line(buildJsonObject { put("type", "link.reveal"); put("ephemeral", b64(publicKey)); put("nonce", b64(nonce)) })
        }
        fun request(request: String): ByteArray {
            check(key.isNotEmpty())
            return line(buildJsonObject { put("type", "link.request"); put("code", request); put("mac", b64(requestMac(key, request))) })
        }
        fun received(raw: String, request: String) {
            val message = read(raw, "link.received", setOf("mac"))
            require(MessageDigest.isEqual(receivedMac(key, request), unb64(text(message, "mac"), 32)))
        }
    }

    /** Ask the local network for main computers that are waiting for a phone. Blocking; call off the main thread. */
    fun discover(timeoutMillis: Int = 1500, port: Int = DISCOVERY_PORT, targets: List<String> = broadcastTargets()): List<Computer> {
        val nonce = b64(ByteArray(16).also { SecureRandom().nextBytes(it) })
        val query = line(buildJsonObject { put("type", "link.discover"); put("version", VERSION); put("nonce", nonce) })
        val found = LinkedHashMap<String, Computer>()
        DatagramSocket().use { socket ->
            socket.broadcast = true
            for (target in targets) runCatching { socket.send(DatagramPacket(query, query.size, InetAddress.getByName(target), port)) }
            val deadline = System.nanoTime() + timeoutMillis * 1_000_000L
            val buffer = ByteArray(1024)
            while (System.nanoTime() < deadline) {
                socket.soTimeout = maxOf(1, ((deadline - System.nanoTime()) / 1_000_000L).toInt())
                val packet = DatagramPacket(buffer, buffer.size)
                try { socket.receive(packet) } catch (_: SocketTimeoutException) { break }
                val address = (packet.address as? Inet4Address)?.hostAddress ?: continue
                runCatching {
                    val answer = read(String(packet.data, 0, packet.length, Charsets.UTF_8), "link.here", setOf("version", "nonce", "name", "port"))
                    val portValue = answer.getValue("port").jsonPrimitive.let { require(!it.isString && it.booleanOrNull == null); it.int }
                    require(answer["version"] == JsonPrimitive(VERSION) && text(answer, "nonce") == nonce && portValue in 1024..65535)
                    require(privateIpv4(address) || (address == "127.0.0.1" && targets == listOf("127.0.0.1")))
                    found["$address:$portValue"] = Computer(cleanName(text(answer, "name")), address, portValue)
                }
            }
        }
        return found.values.toList()
    }
    private fun broadcastTargets(): List<String> = buildList {
        add("255.255.255.255")
        runCatching {
            for (network in NetworkInterface.getNetworkInterfaces()) {
                if (!network.isUp || network.isLoopback) continue
                for (entry in network.interfaceAddresses) {
                    val local = entry.address as? Inet4Address ?: continue
                    val broadcast = entry.broadcast as? Inet4Address ?: continue
                    if (privateIpv4(local.hostAddress.orEmpty())) add(broadcast.hostAddress.orEmpty())
                }
            }
        }
    }.filter { it.isNotEmpty() }.distinct().take(8)

    /** One TCP connection to a discovered computer, kept open while the owner compares codes. */
    class Session(private val computer: Computer, name: String, allowLoopback: Boolean = false) : Closeable {
        val handshake = Handshake(name)
        private val socket = Socket()
        private lateinit var input: InputStream
        init {
            require(privateIpv4(computer.address) || (allowLoopback && computer.address == "127.0.0.1"))
            require(computer.port in 1024..65535)
        }
        private fun readLine(timeoutMillis: Int): String {
            socket.soTimeout = timeoutMillis
            val out = java.io.ByteArrayOutputStream()
            while (true) {
                val next = input.read()
                require(next >= 0)
                if (next == '\n'.code) return out.toString(Charsets.UTF_8.name())
                out.write(next)
                require(out.size() <= MAX_LINE)
            }
        }
        /** Connects and exchanges keys; returns the six-digit code to compare. */
        fun compare(): String {
            socket.connect(InetSocketAddress(InetAddress.getByName(computer.address), computer.port), 5000)
            socket.tcpNoDelay = true
            input = socket.getInputStream().buffered()
            val output = socket.getOutputStream()
            output.write(handshake.hello()); output.flush()
            output.write(handshake.root(readLine(20_000))); output.flush()
            return handshake.code
        }
        /** After the owner confirmed and the phone enrolled: deliver its request, authenticated. */
        fun sendRequest(request: String) {
            socket.getOutputStream().apply { write(handshake.request(request)); flush() }
            handshake.received(readLine(20_000), request)
        }
        override fun close() { runCatching { socket.close() } }
    }
}
