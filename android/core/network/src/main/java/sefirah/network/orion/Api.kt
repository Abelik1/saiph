package sefirah.network.orion

import android.content.Context
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

object Api {
    fun migrateMesh(context: Context) {
        val prefs = context.getSharedPreferences("orion", Context.MODE_PRIVATE)
        val saved = prefs.getString("base_url", MeshOrigin.DEFAULT)!!
        // Preserve a friend's configured Hub even when an older build did not set the marker.
        // Invalid saved origins fail closed in base(); never redirect an existing key to the owner.
        val origin = runCatching { MeshOrigin.validate(saved) }.getOrNull() ?: return
        if (!prefs.getBoolean("mesh_migrated", false) || saved != origin)
            prefs.edit().putString("base_url", origin).putBoolean("mesh_migrated", true).apply()
    }
    fun base(context: Context): String { migrateMesh(context); return MeshOrigin.validate(context.getSharedPreferences("orion", Context.MODE_PRIVATE).getString("base_url", MeshOrigin.DEFAULT)!!) }
    fun request(context:Context,path:String,method:String="GET",json:JSONObject?=null,signed:Boolean=true):String {
        return requestAt(context,base(context),path,method,json,signed)
    }
    private fun requestAt(context:Context,origin:String,path:String,method:String,json:JSONObject?,signed:Boolean):String {
        require(path.startsWith('/') && !path.startsWith("//"))
        val bytes=(json?.toString()?:"").toByteArray(); val url=URL(MeshOrigin.validate(origin)+path); val c=url.openConnection() as HttpURLConnection
        c.instanceFollowRedirects=false; c.requestMethod=method; c.connectTimeout=10000; c.readTimeout=20000; c.setRequestProperty("Accept","application/json")
        if (json!=null){ c.doOutput=true; c.setRequestProperty("Content-Type","application/json") }
        if (signed) Security.signedHeaders(context,method,path,bytes).forEach{(k,v)->c.setRequestProperty(k,v)}
        if (bytes.isNotEmpty()) c.outputStream.use{it.write(bytes)}
        val code=c.responseCode; val stream=if(code in 200..299)c.inputStream else c.errorStream; val text=stream?.bufferedReader()?.use{it.readText()}?:""
        if(code !in 200..299) throw IllegalStateException("HTTP $code")
        return text
    }
    /** A signed GET streamed to a file, for bodies too large to hold as a String. */
    fun download(context:Context,path:String,target:java.io.File){
        val c=URL(base(context)+path).openConnection() as HttpURLConnection
        c.instanceFollowRedirects=false; c.connectTimeout=10000; c.readTimeout=60000
        Security.signedHeaders(context,"GET",path,ByteArray(0)).forEach{(k,v)->c.setRequestProperty(k,v)}
        val code=c.responseCode
        if(code !in 200..299) throw IllegalStateException("HTTP $code")
        c.inputStream.use{input->target.outputStream().use{input.copyTo(it)}}
    }
    @Synchronized fun pair(context:Context,baseUrl:String,code:String,name:String,meshLoginServer:String?=null):String {
        val prefs=context.getSharedPreferences("orion",Context.MODE_PRIVATE)
        check(!prefs.contains("device_id")) { "Already paired" }
        val origin=MeshOrigin.validate(baseUrl)
        require(code.matches(Regex("[0-9]{8}")))
        val login=meshLoginServer?.let(MeshOrigin::loginServer)
        val body=JSONObject().put("code",code).put("name",name).put("public_key_der_b64",Security.publicKeyB64())
        val id=JSONObject(requestAt(context,origin,"/v1/pairing/claim","POST",body,false)).getString("device_id")
        Enrollment.deviceId(id)
        val edit=prefs.edit().putString("base_url",origin).putBoolean("mesh_migrated",true).putString("device_id",id)
            .remove("pending_enrollment")
        if(login==null)edit.remove("mesh_login_server") else edit.putString("mesh_login_server",login)
        check(edit.commit()) { "Pairing could not be saved" }; return id
    }
    /** Notices and calendar suggestions, newest first; shared with the desktop and laptop. */
    fun inbox(context:Context):org.json.JSONArray = JSONObject(request(context,"/v1/inbox")).getJSONArray("items")
    /** accept / dismiss a suggestion, or done for a notice. The first decision on any device wins. */
    fun decide(context:Context,id:String,decision:String):JSONObject = JSONObject(request(context,"/v1/inbox/$id/decide","POST",JSONObject().put("decision",decision)))
    fun registerPush(context:Context,token:String){ if(context.getSharedPreferences("orion",Context.MODE_PRIVATE).getString("device_id",null)==null)return; request(context,"/v1/devices/push-token","POST",JSONObject().put("token",token),true) }
}
