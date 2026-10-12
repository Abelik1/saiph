package sefirah.network.orion

import android.content.Context
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.serialization.json.*
import okhttp3.*
import java.io.IOException
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import javax.inject.Singleton
import sefirah.domain.model.ThreadInfo

@Singleton
class OrionLink @Inject constructor(private val context: Context) {
    val status = MutableStateFlow("Waiting for setup")
    private val protocol = LinkProtocol()
    private val client = OkHttpClient.Builder().connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.SECONDS).pingInterval(15, TimeUnit.SECONDS)
        .followRedirects(false).followSslRedirects(false).build()
    @Volatile private var socket: WebSocket? = null
    @Volatile private var socketIdentity: String? = null
    fun refreshCapabilities() {
        // Settings changes discard private intent even while disconnected.
        protocol.discardDenied(OrionPermissions.read(context)::allowsPublication)
        val caps = mutableListOf("battery", "inbox", "focus")
        caps += OrionPermissions.read(context).capabilities()
        if(context.getSharedPreferences("orion",0).getBoolean("worker_ready",false) && context.getSharedPreferences("orion",0).getBoolean("clipboard_enabled",true)) caps += "clipboard"
        socket?.send(buildJsonObject { put("op", "hello"); put("capabilities", JsonArray(caps.map(::JsonPrimitive))) }.toString())
    }
    private fun pairedIdentity() = context.getSharedPreferences("orion", Context.MODE_PRIVATE).getString("device_id", null)
    private fun identity(): String? {
        val current=pairedIdentity()
        protocol.identity(current)
        // Pending actions from a repaired pairing cannot use the old signed socket.
        if(socket != null && socketIdentity != current) { socket?.cancel();socket=null }
        return current
    }
    fun knownConversations(): List<ThreadInfo> {
        identity()
        return protocol.knownConversations().map { (thread, checksum) -> ThreadInfo(thread, checksum) }
    }
    fun invalidateConversations() = protocol.invalidateConversations()
    fun publish(type: String, payload: JsonObject, target: String? = null, conversationChecksum: Long? = null): Boolean {
        identity()
        if (!OrionPermissions.read(context).allowsPublication(type)) return false
        val queued = protocol.publish(type, payload, target?.let(::listOf), conversationChecksum)
        flush(); return queued
    }
    private fun flush(retry: Boolean = false) {
        val access = OrionPermissions.read(context)
        socket?.let { ws -> protocol.outgoing(retry,access::allowsPublication).forEach { ws.send(it) } }
    }
    suspend fun run(onConnected: () -> Unit, onEvent: (JsonObject) -> Unit) {
        var retry = 1000L
        while (currentCoroutineContext().isActive) {
            status.value = "Reconnecting automatically"
            try {
                session(onConnected, onEvent)
                retry = 1000
            } catch (cancelled: CancellationException) { throw cancelled }
            catch (_: Exception) { /* Never log headers, keys, frames or exception bodies. */ }
            delay(retry + kotlin.random.Random.nextLong(250))
            retry = (retry * 2).coerceAtMost(15000)
        }
    }
    private suspend fun session(onConnected: () -> Unit, onEvent: (JsonObject) -> Unit) = coroutineScope {
        val sessionIdentity=identity()
        val frames = Channel<String>(64)
        val request = Request.Builder().url(Api.base(context).replaceFirst("http://", "ws://") + "/v1/link")
        Security.signedHeaders(context, "GET", "/v1/link", ByteArray(0)).forEach { (key, value) -> request.header(key, value) }
        val ws = client.newWebSocket(request.build(), object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                if(pairedIdentity()!=sessionIdentity) { webSocket.cancel();return }
                socketIdentity=sessionIdentity
                socket = webSocket
                refreshCapabilities()
            }
            override fun onMessage(webSocket: WebSocket, text: String) {
                if (text.toByteArray().size > 65536 || !frames.trySend(text).isSuccess) webSocket.cancel()
            }
            override fun onMessage(webSocket: WebSocket, bytes: okio.ByteString) { webSocket.cancel() }
            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                webSocket.close(code, null); frames.close()
            }
            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) { frames.close() }
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) { frames.close() }
        })
        var lastFrame = System.nanoTime()
        val heartbeat = launch {
            while (isActive) {
                delay(15000)
                if (System.nanoTime() - lastFrame > 45_000_000_000L) { ws.cancel(); frames.close(); break }
                ws.send("""{"op":"ping"}"""); flush(retry = true)
            }
        }
        try {
            for (text in frames) {
                // Buffered old-session frames cannot execute or ACK after repair.
                if(identity()!=sessionIdentity) break
                lastFrame = System.nanoTime()
                val frame = Json.parseToJsonElement(text).jsonObject
                when (frame["op"]?.jsonPrimitive?.content) {
                    "welcome" -> { status.value = "Online"; flush(retry = true); onConnected() }
                    "accepted" -> protocol.accepted(frame.getValue("id").jsonPrimitive.content)
                    "event" -> protocol.receiveForIdentity(sessionIdentity,frame,onEvent)?.let { ws.send(it) }
                    "ping" -> ws.send("""{"op":"pong"}""")
                    "error" -> throw IOException("Link protocol rejected")
                }
            }
        } finally {
            heartbeat.cancel(); frames.cancel(); socket = null;socketIdentity=null; ws.cancel()
            status.value = "Reconnecting automatically"
        }
    }
}
