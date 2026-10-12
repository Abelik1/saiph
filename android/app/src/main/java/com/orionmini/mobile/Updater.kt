package com.orionmini.mobile

import sefirah.network.orion.Api
import com.castle.sefirah.BuildConfig

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import android.net.Uri
import android.os.Build
import android.provider.Settings
import android.widget.Toast
import org.json.JSONObject
import java.io.File
import java.security.MessageDigest

/**
 * Updates the app from the build published on Orion Hub.
 *
 * The download is a signed request, so only this paired phone can fetch it, and
 * the sha256 must match what the hub published. The real guard is Android's:
 * an update signed with a different certificate from the installed app is
 * refused, so whoever controls the Pi still cannot replace this app.
 */
object Updater {
    fun latest(context: Context): JSONObject? =
        JSONObject(Api.request(context, "/v1/app/android")).optJSONObject("release")

    fun isNewer(release: JSONObject) = release.getLong("version_code") > BuildConfig.VERSION_CODE

    fun label(release: JSONObject) = "${release.getString("version_name")} (build ${release.getLong("version_code")})"

    /** Android asks once per app before it may install other APKs. */
    fun canInstall(context: Context) = context.packageManager.canRequestPackageInstalls()

    fun askInstallPermission(context: Context) = context.startActivity(
        Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:${context.packageName}"))
    )

    fun download(context: Context, release: JSONObject): File {
        val file = File(context.cacheDir, "orion-update.apk")
        Api.download(context, "/v1/app/android/apk", file)
        verify(file, release)
        return file
    }

    fun verify(file: File, release: JSONObject) {
        val digest = file.inputStream().use { input ->
            val md = MessageDigest.getInstance("SHA-256"); val buf = ByteArray(1 shl 16)
            while (true) { val n = input.read(buf); if (n < 0) break; md.update(buf, 0, n) }
            md.digest().joinToString("") { "%02x".format(it) }
        }
        if (!digest.equals(release.getString("sha256"), ignoreCase = true)) {
            file.delete(); throw IllegalStateException("The download does not match the published build. Try again.")
        }
    }

    fun install(context: Context, apk: File) {
        val installer = context.packageManager.packageInstaller
        val params = PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL)
            .apply { setAppPackageName(context.packageName) }
        val id = installer.createSession(params)
        installer.openSession(id).use { session ->
            session.openWrite("orion.apk", 0, apk.length()).use { out ->
                apk.inputStream().use { it.copyTo(out) }; session.fsync(out)
            }
            // The system fills in the result, so the intent must be mutable; it is explicit to our receiver.
            val flags = PendingIntent.FLAG_UPDATE_CURRENT or (if (Build.VERSION.SDK_INT >= 31) PendingIntent.FLAG_MUTABLE else 0)
            val status = PendingIntent.getBroadcast(context, id, Intent(context, InstallResultReceiver::class.java), flags)
            session.commit(status.intentSender)
        }
    }
}

class InstallResultReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        when (intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE)) {
            PackageInstaller.STATUS_PENDING_USER_ACTION -> {
                val confirm = if (Build.VERSION.SDK_INT >= 33) intent.getParcelableExtra(Intent.EXTRA_INTENT, Intent::class.java)
                    else @Suppress("DEPRECATION") intent.getParcelableExtra(Intent.EXTRA_INTENT)
                confirm?.let { context.startActivity(it.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
            }
            PackageInstaller.STATUS_SUCCESS -> File(context.cacheDir, "orion-update.apk").delete()
            else -> Toast.makeText(context,
                "Update not installed: " + (intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE) ?: "unknown error"),
                Toast.LENGTH_LONG).show()
        }
    }
}
