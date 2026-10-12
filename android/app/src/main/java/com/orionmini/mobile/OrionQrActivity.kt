package com.orionmini.mobile

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import com.castle.sefirah.presentation.sync.CameraPreview
import sefirah.network.orion.MeshOrigin
import java.util.concurrent.atomic.AtomicBoolean

class OrionQrActivity : ComponentActivity() {
    private val scanned = AtomicBoolean(false)
    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED)
            requestPermissions(arrayOf(Manifest.permission.CAMERA), 47)
        else camera()
    }
    private fun camera() = setContent {
        CameraPreview({ qr ->
            if (runCatching { MeshOrigin.pairing(qr) }.isSuccess && scanned.compareAndSet(false, true)) runOnUiThread {
                // Extras are omitted from Android's Intent URI logs; never put the code in an internal data URI.
                startActivity(Intent(this, OrionActivity::class.java).putExtra("orion_pairing_qr", qr).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP)); finish()
            }
        }, this)
    }
    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED) camera() else finish()
    }
}
