package com.orionmini.mobile

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import com.castle.sefirah.presentation.sync.CameraPreview
import sefirah.network.orion.HostedApprovalCodes
import sefirah.network.orion.MeshOrigin
import java.util.concurrent.atomic.AtomicBoolean

class OrionQrActivity : ComponentActivity() {
    private val scanned = AtomicBoolean(false)
    private val hostedRoot by lazy { intent.getBooleanExtra(HOSTED_ROOT, false) }
    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED)
            requestPermissions(arrayOf(Manifest.permission.CAMERA), 47)
        else camera()
    }
    private fun camera() = setContent {
        CameraPreview({ qr ->
            if (hostedRoot) {
                // Only a well-formed, signed and unexpired root code returns; the caller
                // still requires full fingerprint comparison before any trust is pinned.
                if (runCatching { HostedApprovalCodes.inspect(qr) }.isSuccess && scanned.compareAndSet(false, true)) runOnUiThread {
                    setResult(Activity.RESULT_OK, Intent().putExtra(HOSTED_ROOT_CODE, qr)); finish()
                }
            } else if (runCatching { MeshOrigin.pairing(qr) }.isSuccess && scanned.compareAndSet(false, true)) runOnUiThread {
                // Extras are omitted from Android's Intent URI logs; never put the code in an internal data URI.
                startActivity(Intent(this, OrionActivity::class.java).putExtra("orion_pairing_qr", qr).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP)); finish()
            }
        }, this)
    }
    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED) camera() else finish()
    }
    companion object {
        private const val HOSTED_ROOT = "hosted_root"
        const val HOSTED_ROOT_CODE = "hosted_root_code"
        fun hostedRoot(context: Context) = Intent(context, OrionQrActivity::class.java).putExtra(HOSTED_ROOT, true)
    }
}
