package sefirah.network.orion

import android.Manifest
import android.content.ContentUris
import android.content.ContentValues
import android.content.Context
import android.graphics.Bitmap
import android.net.Uri
import android.os.Environment
import android.provider.MediaStore
import android.provider.OpenableColumns
import android.util.Size
import io.ktor.http.*
import io.ktor.server.cio.CIO
import io.ktor.server.engine.*
import io.ktor.server.request.*
import io.ktor.server.response.*
import io.ktor.server.routing.*
import kotlinx.coroutines.*
import kotlinx.serialization.json.*
import org.json.JSONObject
import java.io.File
import java.net.NetworkInterface
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import javax.inject.Inject
import javax.inject.Singleton

/** Heavy content remains on the phone; only bounded metadata enters the hub bus. */
@Singleton
class OrionDirectFiles @Inject constructor(private val context: Context,private val link: OrionLink) {
    private data class Item(val file: File,val expires: Long,val photo: Uri? = null)
    private val items=ConcurrentHashMap<String,Item>()
    private val scope=CoroutineScope(SupervisorJob()+Dispatchers.IO)
    private var server: EmbeddedServer<*,*>?=null
    private var host: String?=null
    private var nextPhotos=0L
    private val photoCache=mutableMapOf<Long,Pair<Long,JsonObject>>()
    private val transfers=context.getSharedPreferences("orion_file_transfers",0)
    private val transferLock=Any()
    private val activeTransfers=mutableSetOf<String>()
    init { scope.launch {
        while(isActive) {
            runCatching { discardExpiredTransfers() } // Retry a temporary preference/provider failure next poll.
            val queued=transfers.all.filter { it.key.startsWith("pending:") }
            for((key,value) in queued) {
                val event=runCatching { Json.parseToJsonElement(value as String).jsonObject }.getOrNull()
                if(event==null) { transfers.edit().remove(key).commit();continue }
                val id=key.removePrefix("pending:")
                val claimed=synchronized(transferLock) {
                    if(!transfers.contains(key) || FileTransferExpiry.expired(event,System.currentTimeMillis()/1000.0))false
                    else { activeTransfers.add(id);true }
                }
                if(!claimed)continue
                try { receive(event);transfers.edit().remove(key).commit() }
                catch(_: Exception) { /* Persisted metadata is retried without blocking the Link receive loop. */ }
                finally { synchronized(transferLock) { activeTransfers.remove(id) } }
            }
            delay(15_000)
        }
    } }
    fun enqueue(event: JsonObject) {
        val id=event.getValue("id").jsonPrimitive.content
        synchronized(transferLock) {
            discardExpiredTransfers()
            if(transfers.contains("done:$id") || FileTransferExpiry.expired(event,System.currentTimeMillis()/1000.0))return
            check(transfers.all.count { it.key.startsWith("pending:") }<20 || transfers.contains("pending:$id"))
            check(transfers.edit().putString("pending:$id",event.toString()).commit())
        }
    }
    private fun discardExpiredTransfers() = synchronized(transferLock) {
        for(id in FileTransferExpiry.pending(transfers.all,System.currentTimeMillis()/1000.0)) {
            if(id in activeTransfers)continue
            // Never remove a completed personal download or its deduplication receipt.
            if(!transfers.contains("done:$id"))transfers.getString("uri:$id",null)?.let { value ->
                runCatching { context.contentResolver.delete(Uri.parse(value),null,null) }
            }
            check(transfers.edit().remove("pending:$id").remove("uri:$id").commit())
        }
    }
    private fun mesh(value: String): Boolean=MeshOrigin.isAddress(value)
    @Synchronized private fun start(): Boolean {
        if(server!=null)return true
        val address=NetworkInterface.getNetworkInterfaces().toList().flatMap { it.inetAddresses.toList() }.firstOrNull { mesh(it.hostAddress.orEmpty()) }?.hostAddress ?: return false
        val owner=context.getSharedPreferences("orion",0).getString("device_id","")!!
        server=embeddedServer(CIO,host=address,port=8767) {
            routing { get("/v1/peer/{owner}/blobs/{id}") {
                try {
                    require(mesh(call.request.local.remoteHost) && call.parameters["owner"]==owner)
                    prune();val item=this@OrionDirectFiles.items[call.parameters["id"]] ?: run { call.respond(HttpStatusCode.NotFound);return@get }
                    val proof=JSONObject()
                    listOf("X-Orion-Device-Id","X-Orion-Timestamp","X-Orion-Nonce","X-Orion-Signature").forEach {
                        val value=call.request.headers[it];require(!value.isNullOrEmpty() && value.length<=1024);proof.put(it,value)
                    }
                    withContext(Dispatchers.IO) { Api.request(context,"/v1/link/peer/verify","POST",JSONObject().put("path",call.request.uri).put("headers",proof)) }
                    // Cached thumbnails/originals must not outlive the underlying OS access.
                    if(item.photo != null && (!OrionPermissions.read(context).photos || runCatching {
                        context.contentResolver.openFileDescriptor(item.photo,"r")?.use { true } ?: false
                    }.getOrDefault(false).not())) {
                        this@OrionDirectFiles.items.remove(call.parameters["id"]);item.file.delete()
                        call.respond(HttpStatusCode.Forbidden);return@get
                    }
                    call.response.header(HttpHeaders.CacheControl,"no-store");call.respondFile(item.file)
                } catch (_: Exception) { call.respond(HttpStatusCode.Forbidden) }
            } }
        }.start(wait=false);host=address;return true
    }
    private fun prune() { items.entries.removeIf { if(it.value.expires<System.currentTimeMillis()) { it.value.file.delete();true } else false } }
    @Synchronized fun stop() { server?.stop(100,1000);server=null;host=null;items.values.forEach { it.file.delete() };items.clear();photoCache.clear();nextPhotos=0 }
    private fun offer(file: File,name: String,mime: String,photo: Uri? = null): JsonObject {
        require(start());prune();require(items.size<150 && file.length()<=MAX_FILE)
        val digest=MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input->val buffer=ByteArray(65536);while(true) { val n=input.read(buffer);if(n<0)break;digest.update(buffer,0,n) } }
        val id=UUID.randomUUID().toString();items[id]=Item(file,System.currentTimeMillis()+900_000,photo)
        return buildJsonObject { put("name",safeName(name));put("mime",mime.take(120));put("size",file.length());put("sha256",digest.digest().joinToString("") { "%02x".format(it) });put("blob",buildJsonObject { put("id",id);put("address",host!!);put("port",8767) }) }
    }
    private fun copyUri(uri: Uri): File {
        val file=File(context.cacheDir,"orion-file-"+UUID.randomUUID());var size=0L
        try { context.contentResolver.openInputStream(uri)!!.use { input->file.outputStream().use { output->val buffer=ByteArray(65536);while(true) { val n=input.read(buffer);if(n<0)break;size+=n;require(size<=MAX_FILE);output.write(buffer,0,n) } } };return file }
        catch(e: Exception) { file.delete();throw e }
    }
    suspend fun share(uri: Uri,target: String,destination: String = "downloads"): Boolean = withContext(Dispatchers.IO) {
        require(destination in setOf("downloads","cloud"))
        val name=context.contentResolver.query(uri,arrayOf(OpenableColumns.DISPLAY_NAME),null,null,null)?.use { if(it.moveToFirst())it.getString(0) else null } ?: "Shared file"
        val file=copyUri(uri)
        try { link.publish("file.offer",JsonObject(offer(file,name,context.contentResolver.getType(uri) ?: "application/octet-stream")+mapOf("destination" to JsonPrimitive(destination))),target) }
        catch (_: Exception) { file.delete();false }
    }
    suspend fun shareText(text: String,target: String,destination: String = "downloads"): Boolean=withContext(Dispatchers.IO) {
        require(destination in setOf("downloads","cloud"))
        val file=File(context.cacheDir,"orion-text-"+UUID.randomUUID());file.writeText(text)
        try { link.publish("file.offer",JsonObject(offer(file,"Shared text.txt","text/plain")+mapOf("destination" to JsonPrimitive(destination))),target) }
        catch(_: Exception) { file.delete();false }
    }
    /** A photo just taken for one computer: offered as a file, then marked ready to paste there. */
    suspend fun capture(file: File,target: String): Boolean=withContext(Dispatchers.IO) {
        try {
            val name="Photo "+java.time.LocalDateTime.now().format(java.time.format.DateTimeFormatter.ofPattern("yyyy-MM-dd HH.mm.ss"))+".jpg"
            val offer=offer(file,name,"image/jpeg")
            link.publish("file.offer",offer,target) && link.publish("capture.insert",buildJsonObject { put("sha256",offer.getValue("sha256")) },target)
        } catch(_: Exception) { file.delete();false }
    }
    fun refreshPhotoAccess(): Boolean {
        if(OrionPermissions.read(context).photos)return true
        items.entries.removeIf { (_,item) -> if(item.photo!=null) { item.file.delete();true } else false }
        photoCache.clear();nextPhotos=0L
        return false
    }
    suspend fun refreshPhotos() {
        if(!refreshPhotoAccess() || System.currentTimeMillis()<nextPhotos)return
        if(!start())return
        nextPhotos=System.currentTimeMillis()+120_000
        val photos=mutableListOf<JsonObject>()
        context.contentResolver.query(MediaStore.Images.Media.EXTERNAL_CONTENT_URI,arrayOf(MediaStore.Images.Media._ID,MediaStore.Images.Media.DISPLAY_NAME,MediaStore.Images.Media.DATE_ADDED),null,null,"${MediaStore.Images.Media.DATE_ADDED} DESC")?.use { cursor->
            var count=0
            while(count++<100 && cursor.moveToNext()) {
                val id=cursor.getLong(0);val name=cursor.getString(1) ?: "Photo.jpg";val timestamp=cursor.getLong(2)*1000
                val uri=ContentUris.withAppendedId(MediaStore.Images.Media.EXTERNAL_CONTENT_URI,id)
                runCatching {
                    val cached=photoCache[id]?.takeIf { it.first>System.currentTimeMillis() }?.second
                    val value=cached ?: run {
                        val bitmap=context.contentResolver.loadThumbnail(uri,Size(240,240),null)
                        val file=File(context.cacheDir,"orion-thumbnail-"+UUID.randomUUID())
                        file.outputStream().use { bitmap.compress(Bitmap.CompressFormat.JPEG,75,it) };bitmap.recycle()
                        val metadata=offer(file,name,"image/jpeg",uri);photoCache[id]=Pair(System.currentTimeMillis()+850_000,metadata);metadata
                    }
                    photos+=buildJsonObject { put("id",id.toString());put("name",safeName(name));put("timestamp",timestamp);put("thumbnail",value) }
                }
            }
        }
        photos.chunked(10).forEach { link.publish("photos.index",buildJsonObject { put("photos",JsonArray(it)) }) }
        link.publish("photos.sync",buildJsonObject { put("ids",JsonArray(photos.map { it.getValue("id") })) })
    }
    fun sendOriginal(id: String,target: String) { scope.launch {
        if("photos" !in OrionPhoneFeatures.capabilities(context))return@launch
        val uri=ContentUris.withAppendedId(MediaStore.Images.Media.EXTERNAL_CONTENT_URI,id.toLong())
        runCatching {
            val name=context.contentResolver.query(uri,arrayOf(MediaStore.Images.Media.DISPLAY_NAME),null,null,null)?.use { if(it.moveToFirst())it.getString(0) else null } ?: "Photo.jpg"
            val value=offer(copyUri(uri),name,context.contentResolver.getType(uri) ?: "image/jpeg",uri)
            link.publish("photo.original",JsonObject(value+mapOf("photo_id" to JsonPrimitive(id))),target)
        }
    } }
    fun receive(event: JsonObject) {
        val eventId=event.getValue("id").jsonPrimitive.content
        if(transfers.contains("done:$eventId"))return
        val payload=event.getValue("payload").jsonObject;val size=payload.getValue("size").jsonPrimitive.long;require(size in 0..MAX_FILE)
        val blob=payload.getValue("blob").jsonObject;val address=blob.getValue("address").jsonPrimitive.content;require(mesh(address))
        val port=blob.getValue("port").jsonPrimitive.int;require(port in 1024..65535)
        val id=blob.getValue("id").jsonPrimitive.content;require(UUID.fromString(id).toString()==id)
        val path="/v1/peer/${event.getValue("source").jsonPrimitive.content}/blobs/$id"
        val connection=URL(MeshOrigin.endpoint(address,port,path)).openConnection() as HttpURLConnection
        connection.instanceFollowRedirects=false;connection.connectTimeout=10000;connection.readTimeout=30000
        Security.signedHeaders(context,"GET",path,ByteArray(0)).forEach { (k,v)->connection.setRequestProperty(k,v) }
        val file=File(context.cacheDir,"orion-download-"+UUID.randomUUID());var total=0L;val digest=MessageDigest.getInstance("SHA-256")
        try {
            require(connection.responseCode==200 && connection.contentLengthLong==size)
            connection.inputStream.use { input->file.outputStream().use { output->val buffer=ByteArray(65536);while(true) { val n=input.read(buffer);if(n<0)break;total+=n;require(total<=size);output.write(buffer,0,n);digest.update(buffer,0,n) } } }
            require(total==size && digest.digest().joinToString("") { "%02x".format(it) }==payload.getValue("sha256").jsonPrimitive.content)
            val values=ContentValues().apply { put(MediaStore.Downloads.DISPLAY_NAME,safeName(payload.getValue("name").jsonPrimitive.content));put(MediaStore.Downloads.MIME_TYPE,payload.getValue("mime").jsonPrimitive.content);put(MediaStore.Downloads.RELATIVE_PATH,Environment.DIRECTORY_DOWNLOADS+"/Orion");put(MediaStore.Downloads.IS_PENDING,1) }
            val uri=transfers.getString("uri:$eventId",null)?.let(Uri::parse) ?: context.contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI,values)!!.also {
                check(transfers.edit().putString("uri:$eventId",it.toString()).commit())
            }
            try {
                context.contentResolver.openOutputStream(uri,"wt")!!.use { output->file.inputStream().use { it.copyTo(output) } }
                values.clear();values.put(MediaStore.Downloads.IS_PENDING,0);context.contentResolver.update(uri,values,null,null)
                check(transfers.edit().putLong("done:$eventId",System.currentTimeMillis()).putString("received:$eventId",uri.toString()).remove("uri:$eventId").commit())
                // Completion IDs remain longer than Link's deduplication window.
                val expired=transfers.all.filter { it.key.startsWith("done:") && System.currentTimeMillis()-(it.value as? Long ?: 0)>172800000L }
                val edit=transfers.edit();expired.keys.forEach(edit::remove);edit.apply()
            } catch(e: Exception) { context.contentResolver.delete(uri,null,null);transfers.edit().remove("uri:$eventId").commit();throw e }
        } finally { file.delete();connection.disconnect() }
    }
    companion object {
        const val MAX_FILE=2L*1024*1024*1024
        fun safeName(value: String)=value.substringAfterLast('/').substringAfterLast('\\').replace(Regex("[\\x00-\\x1f<>:\"/\\\\|?*]"),"_").trim(' ','.').take(180).ifBlank { "Shared file" }
    }
}
