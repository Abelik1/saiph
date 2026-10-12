package sefirah.network.orion

import android.content.Context
import io.ktor.http.*
import io.ktor.server.cio.CIO
import io.ktor.server.engine.*
import io.ktor.server.request.*
import io.ktor.server.response.*
import io.ktor.server.routing.*
import kotlinx.coroutines.*
import kotlinx.serialization.json.*
import org.json.JSONObject
import sefirah.clipboard.ClipboardFeature
import sefirah.domain.model.ClipboardInfo
import sefirah.common.util.getFileProviderUri
import java.io.File
import java.net.NetworkInterface
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class OrionPeer @Inject constructor(private val context: Context, private val link: OrionLink) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    val clipboardCache = ClipboardCache()
    private data class Offered(val file: File, val expires: Long)
    private val files = ConcurrentHashMap<String, Offered>()
    private var server: EmbeddedServer<*, *>? = null
    private var address: String? = null
    private fun clipboardEnabled() = context.getSharedPreferences("orion",0).getBoolean("clipboard_enabled",true)
    private fun mesh(value: String): Boolean = MeshOrigin.isAddress(value)
    @Synchronized fun start(): Boolean {
        if (server != null) return true
        val host = NetworkInterface.getNetworkInterfaces().toList().flatMap { it.inetAddresses.toList() }
            .firstOrNull { mesh(it.hostAddress.orEmpty()) }?.hostAddress ?: return false
        val device = context.getSharedPreferences("orion",0).getString("device_id","")!!
        server = embeddedServer(CIO, host=host, port=8766) {
            routing {
                get("/v1/peer/{owner}/blobs/{id}") {
                    try {
                        if (!mesh(call.request.local.remoteHost) || call.parameters["owner"] != device) {
                            call.respond(HttpStatusCode.Forbidden); return@get
                        }
                        prune()
                        val item = files[call.parameters["id"]] ?: run { call.respond(HttpStatusCode.NotFound); return@get }
                        val names = listOf("X-Orion-Device-Id","X-Orion-Timestamp","X-Orion-Nonce","X-Orion-Signature")
                        val headers = JSONObject()
                        for (name in names) {
                            val value = call.request.headers[name]
                            if (value.isNullOrEmpty() || value.length>1024) { call.respond(HttpStatusCode.Unauthorized); return@get }
                            headers.put(name,value)
                        }
                        withContext(Dispatchers.IO) { Api.request(context,"/v1/link/peer/verify","POST",
                            JSONObject().put("path",call.request.uri).put("headers",headers)) }
                        call.response.header(HttpHeaders.CacheControl,"no-store")
                        call.respondFile(item.file)
                    } catch (_: Exception) { call.respond(HttpStatusCode.Forbidden) }
                }
            }
        }.start(wait=false)
        address=host
        return true
    }
    private fun prune() {
        files.entries.removeIf { entry ->
            if (entry.value.expires < System.currentTimeMillis()) { entry.value.file.delete();true } else false
        }
    }
    @Synchronized fun stop() {
        server?.stop(100,1000);server=null;address=null
        files.values.forEach { it.file.delete() };files.clear()
    }
    fun sendText(text: String): Boolean {
        if (!clipboardEnabled()) return false
        val bytes=text.toByteArray();val digest=ClipboardCache.hash(bytes)
        if (!clipboardCache.claim("text/plain",digest)) return true
        if (text.length<=4096) return link.publish("clipboard",buildJsonObject {
            put("mime","text/plain");put("text",text);put("sha256",digest);put("size",bytes.size)
        })
        val file=File(context.cacheDir,"orion-clipboard-"+UUID.randomUUID())
        file.writeBytes(bytes)
        return sendFile("text/plain",file,alreadyClaimed=true)
    }
    fun sendFile(mime: String, file: File, alreadyClaimed: Boolean=false): Boolean {
        scope.launch {
            try {
                if (!clipboardEnabled()) { file.delete();return@launch }
                if (!start()) { file.delete();return@launch }
                val digest=MessageDigest.getInstance("SHA-256")
                file.inputStream().use { input -> val buf=ByteArray(65536);while(true) { val n=input.read(buf);if(n<0)break;digest.update(buf,0,n) } }
                val hash=digest.digest().joinToString("") { "%02x".format(it) }
                if (!alreadyClaimed && !clipboardCache.claim(mime,hash)) { file.delete();return@launch }
                prune()
                if (files.size>=8) { file.delete();return@launch }
                val id=UUID.randomUUID().toString();val size=file.length()
                files[id]=Offered(file,System.currentTimeMillis()+300_000)
                if (!clipboardEnabled()) { files.remove(id);file.delete();return@launch }
                link.publish(if(size<=MAX_CLIPBOARD) "clipboard" else "file.offer",buildJsonObject {
                    put("mime",mime);put("sha256",hash);put("size",size)
                    if(size>MAX_CLIPBOARD) put("name","Clipboard image."+mime.substringAfter('/'))
                    put("blob",buildJsonObject { put("id",id);put("address",address!!);put("port",8766) })
                })
            } catch (_: Exception) { file.delete() }
        }
        return true
    }
    fun receiveClipboard(event: JsonObject, clipboard: ClipboardFeature) {
        if (!clipboardEnabled()) return
        val body=event.getValue("payload").jsonObject
        val mime=body.getValue("mime").jsonPrimitive.content
        val hash=body.getValue("sha256").jsonPrimitive.content
        if (body["text"] != null) {
            if (!clipboardCache.claim(mime,hash)) return
            clipboard.setClipboard(ClipboardInfo("text/plain",body.getValue("text").jsonPrimitive.content));return
        }
        val size=body.getValue("size").jsonPrimitive.long
        require(size in 0..MAX_CLIPBOARD)
        val blob=body.getValue("blob").jsonObject;val host=blob.getValue("address").jsonPrimitive.content
        require(mesh(host));val port=blob.getValue("port").jsonPrimitive.int;require(port in 1024..65535)
        val id=blob.getValue("id").jsonPrimitive.content;require(UUID.fromString(id).toString()==id)
        val owner=event.getValue("source").jsonPrimitive.content
        val path="/v1/peer/$owner/blobs/$id"
        val connection=URL(MeshOrigin.endpoint(host,port,path)).openConnection() as HttpURLConnection
        connection.instanceFollowRedirects=false;connection.connectTimeout=10000;connection.readTimeout=20000
        Security.signedHeaders(context,"GET",path,ByteArray(0)).forEach { (k,v)->connection.setRequestProperty(k,v) }
        val file=File(context.cacheDir,"orion-received-"+UUID.randomUUID()+"."+mime.substringAfter('/'))
        try {
            require(connection.responseCode==200 && connection.contentLengthLong==size)
            val digest=MessageDigest.getInstance("SHA-256")
            var total=0L
            connection.inputStream.use { input -> file.outputStream().use { output ->
                val buffer=ByteArray(65536);while(true) { val n=input.read(buffer);if(n<0)break;total+=n
                    require(total<=size);output.write(buffer,0,n);digest.update(buffer,0,n) }
            } }
            require(total==size && digest.digest().joinToString("") { "%02x".format(it) }==hash)
            if (!clipboardEnabled() || !clipboardCache.claim(mime,hash)) { file.delete();return }
            if (mime=="text/plain") { clipboard.setClipboard(ClipboardInfo(mime,file.readText()));file.delete() }
            else clipboard.setClipboardUri(getFileProviderUri(context,file))
        } finally { connection.disconnect() }
    }
    companion object { const val MAX_CLIPBOARD=25L*1024*1024 }
}
