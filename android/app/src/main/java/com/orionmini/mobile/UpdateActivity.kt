package com.orionmini.mobile

import android.app.Activity
import android.os.Bundle
import android.widget.TextView
import org.json.JSONObject
import kotlin.concurrent.thread

/** A notification starts the download; only Android's required install consent remains. */
class UpdateActivity : Activity() {
    private lateinit var status: TextView
    private var busy = false
    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        status = text("Preparing update…").apply { setPadding(dp(24), dp(64), dp(24), dp(24)) }
        setContentView(status)
    }
    override fun onResume() {
        super.onResume()
        if (busy) return
        if (!Updater.canInstall(this)) { Updater.askInstallPermission(this); return }
        busy = true
        thread {
            runCatching {
                val cached = getSharedPreferences("orion", MODE_PRIVATE).getString("pending_android_release", null)?.let(::JSONObject)
                val release = cached?.takeIf { Updater.isNewer(it) } ?: Updater.latest(this)
                if (release != null && Updater.isNewer(release)) {
                    val file = java.io.File(cacheDir, "orion-update.apk")
                    val apk = if (cached === release && file.exists()) file.apply { Updater.verify(this, release) }
                        else Updater.download(this, release)
                    Updater.install(this, apk)
                }
            }.onSuccess { runOnUiThread { finish() } }
                .onFailure { runOnUiThread { status.text = "Update unavailable. Saiph will check again automatically."; busy = false } }
        }
    }
}
