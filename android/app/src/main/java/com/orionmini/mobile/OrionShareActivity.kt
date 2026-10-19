package com.orionmini.mobile

import android.app.AlertDialog
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.lifecycle.lifecycleScope
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.*
import org.json.JSONObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import sefirah.network.orion.Api
import sefirah.network.orion.OrionDirectFiles
import sefirah.network.orion.OrionLink
import javax.inject.Inject

/** Explicit Android share gesture; targets come from Orion's paired-device store. */
@AndroidEntryPoint
class OrionShareActivity : ComponentActivity() {
    @Inject lateinit var files: OrionDirectFiles
    @Inject lateinit var link: OrionLink
    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        val status = text("Choose where to send").apply { setPadding(dp(2), dp(8), 0, 0) }
        ScreenFrame(this, "Send with Saiph", back = ::finish).content.addView(status)
        val hosted = HostedRuntime.get(this)
        if (hosted.enabled()) {
            shareCloud(hosted, status)
            return
        }
        lifecycleScope.launch {
            val targets=withContext(Dispatchers.IO) { runCatching {
                val devices=JSONObject(Api.request(this@OrionShareActivity,"/v1/link/phone")).getJSONArray("devices")
                (0 until devices.length()).map(devices::getJSONObject).filter { device->
                    val caps=device.optJSONArray("capabilities")
                    device.optBoolean("online") && device.getString("id")!=getSharedPreferences("orion",0).getString("device_id",null) && caps!=null && (0 until caps.length()).any { caps.optString(it)=="files" }
                }
            }.getOrNull() }
            if(targets.isNullOrEmpty()) { status.text="Your paired computers are offline. The file has not been sent.";return@launch }
            AlertDialog.Builder(this@OrionShareActivity).setTitle("Send with Saiph")
                .setItems(targets.map { it.getString("name") }.toTypedArray()) { _,index->
                    val device=targets[index].getString("id")
                    val caps=targets[index].getJSONArray("capabilities")
                    val cloud=(0 until caps.length()).any { caps.optString(it)=="cloud.files" }
                    val text=intent.getCharSequenceExtra(Intent.EXTRA_TEXT)?.toString()
                    if(!text.isNullOrBlank()) AlertDialog.Builder(this@OrionShareActivity).setTitle("Share with Saiph")
                        .setItems((listOf("Open on desktop","Send as a text file")+if(cloud)listOf("Save to Cloud") else emptyList()).toTypedArray()) { _,choice->
                            if(choice==0) {
                                val uri=runCatching { java.net.URI(text.trim()) }.getOrNull()
                                val kind=if(uri?.scheme in listOf("http","https") && !uri?.host.isNullOrEmpty() && uri?.userInfo==null)"link" else "text"
                                val ok=text.toByteArray().size<=32768 && link.publish("handoff",buildJsonObject { put("kind",kind);put("value",if(kind=="link")text.trim() else text) },device)
                                status.text=if(ok)"Shared with your computer." else "This text is too long. Send it as a file instead."
                                if(ok) { lifecycleScope.launch { delay(1000);finish() } }
                            } else lifecycleScope.launch { val ok=files.shareText(text,device,if(choice==2)"cloud" else "downloads");status.text=if(ok)"Text queued for your computer." else "The text could not be sent." }
                        }.setNegativeButton("Cancel") { _,_->finish() }.show()
                    else if(cloud) AlertDialog.Builder(this@OrionShareActivity).setTitle("Share with Saiph")
                        .setItems(arrayOf("Send a file","Save to Cloud")) { _,choice->send(device,status,if(choice==1)"cloud" else "downloads") }
                        .setNegativeButton("Cancel") { _,_->finish() }.show()
                    else send(device,status)
                }
                .setNegativeButton("Cancel") { _,_->finish() }.setOnCancelListener { finish() }.show()
        }
    }
    /** Cloud sharing never discovers targets or sends a file through retained Hub settings. */
    private fun shareCloud(runtime: HostedRuntime, status: TextView) {
        lifecycleScope.launch {
            val targets = withContext(Dispatchers.IO) { runCatching { runtime.shareTargets() }.getOrDefault(emptyMap()) }.toList()
            if (targets.isEmpty()) {
                status.text = "No approved computers are connected. Open Saiph on your computer and try again."
                return@launch
            }
            AlertDialog.Builder(this@OrionShareActivity).setTitle("Send with Saiph")
                .setItems(targets.map { it.second.ifBlank { "Approved computer" } }.toTypedArray()) { _, index ->
                    lifecycleScope.launch {
                        status.text = "Preparing your file…"
                        val computer = targets[index].second.ifBlank { "your computer" }
                        // A direct transfer over the local network shows its progress here.
                        val ticker = launch { while (true) {
                            runtime.lan.sending?.let { status.text = HostedTransferText.sending(it.name, it.computer, it.sent, it.size, it.connecting) }
                            delay(500)
                        } }
                        val result = withContext(Dispatchers.IO) { runCatching {
                            @Suppress("DEPRECATION")
                            val uris: List<Uri> = if (intent.action == Intent.ACTION_SEND_MULTIPLE)
                                intent.getParcelableArrayListExtra<Uri>(Intent.EXTRA_STREAM).orEmpty()
                            else listOfNotNull(intent.getParcelableExtra<Uri>(Intent.EXTRA_STREAM))
                            require(uris.size in 1..100 && uris.all { it.scheme == "content" })
                            uris.map { runtime.sendFile(it, targets[index].first) }
                        } }
                        ticker.cancel()
                        val ok = result.isSuccess
                        status.text = result.fold({ HostedTransferText.sent(it, computer) + " Save it in Saiph on that computer." }) { failure ->
                            (failure as? TransferRefused)?.message ?: "The file could not be sent. Check Saiph on both devices and try again."
                        }
                        if (ok) { delay(1500); finish() }
                    }
                }.setNegativeButton("Cancel") { _, _ -> finish() }.setOnCancelListener { finish() }.show()
        }
    }
    private fun send(device: String,status: TextView,destination: String = "downloads") { lifecycleScope.launch {
        status.text="Preparing your file…"
        @Suppress("DEPRECATION")
        val uris: List<Uri> = if(intent.action==Intent.ACTION_SEND_MULTIPLE) intent.getParcelableArrayListExtra<Uri>(Intent.EXTRA_STREAM).orEmpty().take(100)
            else listOfNotNull(intent.getParcelableExtra<Uri>(Intent.EXTRA_STREAM))
        val ok=withContext(Dispatchers.IO) { runCatching {
            require(uris.isNotEmpty());uris.all { files.share(it,device,destination) }
        }.getOrDefault(false) }
        status.text=if(ok) "File queued for your computer." else "The file could not be sent. Check Saiph's status on both devices."
        if(ok) { delay(1000);finish() }
    } }
}
