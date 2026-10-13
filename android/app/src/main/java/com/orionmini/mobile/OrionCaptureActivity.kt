// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.Manifest
import android.app.AlertDialog
import android.content.pm.PackageManager
import android.os.Bundle
import android.widget.TextView
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.FileProvider
import androidx.lifecycle.lifecycleScope
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.*
import org.json.JSONObject
import sefirah.network.orion.Api
import sefirah.network.orion.OrionDirectFiles
import java.io.File
import java.util.UUID
import javax.inject.Inject

/** Take a photo for one paired computer, where it arrives on the clipboard ready to paste. */
@AndroidEntryPoint
class OrionCaptureActivity : ComponentActivity() {
    @Inject lateinit var files: OrionDirectFiles
    private lateinit var status: TextView
    private var target: String? = null
    private var photo: File? = null
    private val take = registerForActivityResult(ActivityResultContracts.TakePicture()) { taken ->
        val file = photo; val device = target
        if (!taken || file == null || device == null || !file.isFile || file.length() == 0L) { file?.delete(); finish(); return@registerForActivityResult }
        status.text = "Sending your photo…"
        lifecycleScope.launch {
            val ok = files.capture(file, device)
            Toast.makeText(this@OrionCaptureActivity, if (ok) "Photo sent. Paste it on your computer." else "The photo could not be sent. Check Saiph on both devices.", Toast.LENGTH_LONG).show()
            finish()
        }
    }
    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        status = TextView(this).apply { text = "Choose a computer"; setPadding(40, 48, 40, 48); textSize = 18f }; setContentView(status)
        target = state?.getString("target"); photo = state?.getString("photo")?.let(::File)
        if (state != null) return // The camera result is delivered to the restored activity.
        lifecycleScope.launch {
            val own = getSharedPreferences("orion", 0).getString("device_id", null)
            val computers = withContext(Dispatchers.IO) { runCatching {
                val devices = JSONObject(Api.request(this@OrionCaptureActivity, "/v1/link/phone")).getJSONArray("devices")
                (0 until devices.length()).map(devices::getJSONObject).filter { device ->
                    val caps = device.optJSONArray("capabilities")
                    device.optBoolean("online") && device.getString("id") != own && caps != null && (0 until caps.length()).any { caps.optString(it) == "files" }
                }
            }.getOrNull() }
            when {
                computers.isNullOrEmpty() -> { status.text = "Your paired computers are offline. No photo was taken." }
                computers.size == 1 -> start(computers[0].getString("id"))
                else -> AlertDialog.Builder(this@OrionCaptureActivity).setTitle("Photo for which computer?")
                    .setItems(computers.map { it.getString("name") }.toTypedArray()) { _, index -> start(computers[index].getString("id")) }
                    .setNegativeButton("Cancel") { _, _ -> finish() }.setOnCancelListener { finish() }.show()
            }
        }
    }
    private fun start(device: String) {
        target = device
        // Saiph declares CAMERA, so Android requires it granted before another camera app may be used.
        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) { requestPermissions(arrayOf(Manifest.permission.CAMERA), 48); return }
        val file = File(cacheDir, "orion-capture-" + UUID.randomUUID() + ".jpg").also { photo = it }
        runCatching { take.launch(FileProvider.getUriForFile(this, "$packageName.fileprovider", file)) }
            .onFailure { file.delete(); status.text = "No camera app is available." }
    }
    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        val device = target
        if (grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED && device != null) start(device) else finish()
    }
    override fun onSaveInstanceState(state: Bundle) {
        target?.let { state.putString("target", it) }; photo?.let { state.putString("photo", it.path) }
        super.onSaveInstanceState(state)
    }
}
