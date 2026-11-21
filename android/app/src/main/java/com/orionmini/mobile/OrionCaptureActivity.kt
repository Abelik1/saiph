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
            val ok = OrionComputers.clipboardImage(this@OrionCaptureActivity, files, file, device, "Photo", "image/jpeg")
            Toast.makeText(this@OrionCaptureActivity, if (ok) "Photo sent. Paste it on your computer." else "The photo could not be sent. Check Saiph on both devices.", Toast.LENGTH_LONG).show()
            finish()
        }
    }
    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        status = text("Choose a computer").apply { setPadding(dp(2), dp(8), 0, 0) }
        ScreenFrame(this, "Photo", back = ::finish).content.addView(status)
        target = state?.getString("target"); photo = state?.getString("photo")?.let(::File)
        if (state != null) return // The camera result is delivered to the restored activity.
        lifecycleScope.launch {
            val computers = withContext(Dispatchers.IO) { runCatching { OrionComputers.targets(this@OrionCaptureActivity, "files") }.getOrNull() }
            when {
                computers.isNullOrEmpty() -> { status.text = "Your computers are offline. No photo was taken." }
                // Saiph Cloud shares a photo with every approved computer, so there is nothing to choose.
                computers.size == 1 || OrionComputers.cloud(this@OrionCaptureActivity) -> start(computers[0].first)
                else -> AlertDialog.Builder(this@OrionCaptureActivity).setTitle("Photo for which computer?")
                    .setItems(computers.map { it.second }.toTypedArray()) { _, index -> start(computers[index].first) }
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
