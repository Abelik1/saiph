// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInfo
import android.content.pm.PackageInstaller
import android.content.pm.PackageManager
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.core.app.ActivityCompat
import androidx.core.app.NotificationCompat
import androidx.core.content.pm.PackageInfoCompat
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.castle.sefirah.BuildConfig
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.CookieJar
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import sefirah.network.orion.Api
import java.io.File
import java.io.IOException
import java.net.Proxy
import java.net.URI
import java.util.concurrent.TimeUnit

/** The source answered, but has no update service for this phone. [message] is for the person. */
class UpdateUnavailable(message: String) : Exception(message)

/**
 * Where this phone's updates come from. Every source is fixed by the build or by the phone's
 * own pairing; none follows a URL it was sent, and none follows redirects.
 */
interface UpdateSource {
    /** Shown in the update screen: "Downloads from …". */
    val place: String
    /** The current published build, or null when nothing is published. */
    suspend fun latest(): AppRelease?
    suspend fun opener(): ResumableDownload.Opener
}

internal object UpdateHttp {
    val client: OkHttpClient by lazy {
        OkHttpClient.Builder().followRedirects(false).followSslRedirects(false).retryOnConnectionFailure(false)
            .cookieJar(CookieJar.NO_COOKIES).proxy(Proxy.NO_PROXY)
            .connectTimeout(10, TimeUnit.SECONDS).readTimeout(30, TimeUnit.SECONDS).build()
    }

    /** A small body, refused past [maximum] bytes. */
    fun small(body: okhttp3.ResponseBody?, maximum: Int = 16 * 1024): ByteArray {
        val input = body?.byteStream() ?: throw IOException("Empty answer")
        return input.use {
            val bytes = it.readNBytesCompat(maximum + 1)
            if (bytes.size > maximum) throw UpdateRefused(UpdateRefused.Reason.MANIFEST)
            bytes
        }
    }

    private fun java.io.InputStream.readNBytesCompat(limit: Int): ByteArray {
        val out = java.io.ByteArrayOutputStream(); val buffer = ByteArray(4096)
        while (out.size() < limit) {
            val count = read(buffer, 0, minOf(buffer.size, limit - out.size()))
            if (count < 0) break
            out.write(buffer, 0, count)
        }
        return out.toByteArray()
    }

    /** One APK request; [offset] > 0 resumes. Identity encoding keeps byte offsets meaningful. */
    fun apk(url: String, offset: Long): ResumableDownload.Answer {
        val request = Request.Builder().url(url).header("Accept-Encoding", "identity")
            .apply { if (offset > 0) header("Range", "bytes=$offset-") }.build()
        val response = client.newCall(request).execute()
        val body = response.body ?: run { response.close(); throw IOException("Empty answer") }
        return ResumableDownload.Answer(response.code, response.header("Content-Range"), body.byteStream())
    }
}

/**
 * The Saiph account: the same protected catalog the website's download page uses, reached with
 * this phone's own account sign-in. The origin is the one packaged into this build
 * (`hosted-defaults.json`); a phone configured for any other deployment gets no Hosted updates.
 * The two routes are proposed in docs/ANDROID_UPDATES.md and are not on the service yet.
 */
class HostedUpdateSource(private val context: Context, private val origin: String) : UpdateSource {
    override val place = "your Saiph account"

    override suspend fun latest(): AppRelease? {
        val token = token()
        val request = Request.Builder().url("$origin/v1/app/android/release").header("Accept", "application/json")
            .header("Authorization", "Bearer $token").build()
        UpdateHttp.client.newCall(request).execute().use { response ->
            return when (response.code) {
                200 -> UpdateManifest.hosted(UpdateHttp.small(response.body))
                204 -> null
                401, 403 -> throw UpdateUnavailable("Sign in to Saiph again, then check for updates.")
                404 -> throw UpdateUnavailable("Your Saiph account doesn't offer app updates yet. Get the latest app from usesaiph.com/downloads.html.")
                else -> throw IOException("Update check failed (HTTP ${response.code})")
            }
        }
    }

    /** Each attempt asks for a fresh five-minute ticket, so a resumed download still works later. */
    override suspend fun opener(): ResumableDownload.Opener {
        val token = token()
        return ResumableDownload.Opener { offset ->
            val ask = Request.Builder().url("$origin/v1/app/android/download").header("Accept", "application/json")
                .header("Authorization", "Bearer $token").post("{}".toRequestBody("application/json".toMediaType())).build()
            val ticket = UpdateHttp.client.newCall(ask).execute().use { response ->
                if (response.code != 200) throw IOException("Download unavailable (HTTP ${response.code})")
                val value = UpdateManifest.parse(UpdateHttp.small(response.body, 1024)) as JsonObject
                check(value.keys == setOf("ticket"))
                value.getValue("ticket").jsonPrimitive.also { check(it.isString) }.content
                    .also { check(Regex("[A-Za-z0-9_-]{43}").matches(it)) }
            }
            // The ticket is the credential: no Authorization header, cookies or query, as the service requires.
            UpdateHttp.apk("$origin/v1/download/$ticket", offset)
        }
    }

    private suspend fun token(): String = try { HostedAccount.get(context).token() }
        catch (cancelled: CancellationException) { throw cancelled }
        catch (_: Exception) { throw UpdateUnavailable("Sign in to Saiph again, then check for updates.") }

    companion object {
        /** This build's own Hosted origin, if it was packaged with one and the phone uses it. */
        fun official(context: Context): String? = runCatching {
            val raw = context.assets.open("hosted-defaults.json").use { it.readBytes() }
            check(raw.size <= 4096)
            val packaged = (Json.parseToJsonElement(raw.toString(Charsets.UTF_8)) as JsonObject).getValue("service_url").jsonPrimitive.content
            val uri = URI(packaged)
            check(uri.scheme == "https" && !uri.host.isNullOrBlank() && uri.rawUserInfo == null && uri.rawQuery == null &&
                uri.rawFragment == null && uri.rawPath in listOf("", "/") && uri.port in listOf(-1, 443))
            packaged.trimEnd('/').takeIf { it == context.getSharedPreferences("orion_hosted", 0).getString("origin", null) }
        }.getOrNull()
    }
}

/** A self-hosted Hub's published build, fetched with this phone's signed pairing. */
class HubUpdateSource(private val context: Context) : UpdateSource {
    override val place = "your Hub"

    override suspend fun latest(): AppRelease? {
        val raw = try { Api.request(context, "/v1/app/android") }
            catch (failure: IllegalStateException) { throw IOException(failure.message) }
        return UpdateManifest.hub(raw.toByteArray())
    }

    override suspend fun opener() = ResumableDownload.Opener { offset ->
        val connection = Api.openSigned(context, "/v1/app/android/apk", offset)
        val code = connection.responseCode
        ResumableDownload.Answer(code, connection.getHeaderField("Content-Range"),
            if (code in 200..299) connection.inputStream else (connection.errorStream ?: java.io.ByteArrayInputStream(ByteArray(0))))
    }
}

object UpdateSources {
    /** Debug override first (debug builds only), then the phone's own pairing: Hub, else Saiph account. */
    fun select(context: Context): UpdateSource? {
        UpdateDebugOverride.source(context)?.let { return it }
        if (context.getSharedPreferences("orion", Context.MODE_PRIVATE).contains("device_id")) return HubUpdateSource(context)
        val hosted = context.getSharedPreferences("orion_hosted", 0)
        if (!hosted.getBoolean("enabled", false)) return null
        return HostedUpdateSource.official(context)?.let { HostedUpdateSource(context, it) }
    }
}

/** Android's view of an APK file and of the installed app. */
object PackageFactsReader {
    @Suppress("DEPRECATION")
    private val flags = if (Build.VERSION.SDK_INT >= 28) PackageManager.GET_SIGNING_CERTIFICATES
        // Android 8.x: the older API. Its FakeID weakness affected Android 4.4 and earlier only.
        else PackageManager.GET_SIGNATURES

    fun archive(context: Context, apk: File): PackageFacts? = runCatching {
        val manager = context.packageManager
        val info = if (Build.VERSION.SDK_INT >= 33) manager.getPackageArchiveInfo(apk.path, PackageManager.PackageInfoFlags.of(flags.toLong()))
            else manager.getPackageArchiveInfo(apk.path, flags)
        info?.let(::facts)
    }.getOrNull()

    fun installed(context: Context): PackageFacts {
        val manager = context.packageManager
        val info = if (Build.VERSION.SDK_INT >= 33) manager.getPackageInfo(context.packageName, PackageManager.PackageInfoFlags.of(flags.toLong()))
            else manager.getPackageInfo(context.packageName, flags)
        return facts(info)
    }

    /** The certificates that signed the APK's contents now, not past ones in a rotation lineage. */
    @Suppress("DEPRECATION")
    private fun facts(info: PackageInfo): PackageFacts {
        val certificates = if (Build.VERSION.SDK_INT >= 28) info.signingInfo?.apkContentsSigners else info.signatures
        return PackageFacts(info.packageName, PackageInfoCompat.getLongVersionCode(info),
            certificates.orEmpty().map { UpdateVerifier.certificate(it.toByteArray()) }.toSet())
    }
}

/** Hands a verified APK to Android's installer. Android always shows its own confirmation. */
object UpdateInstaller {
    fun canInstall(context: Context) = context.packageManager.canRequestPackageInstalls()

    fun permissionSettings(context: Context) =
        Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:${context.packageName}"))

    fun install(context: Context, apk: File, release: AppRelease) {
        val installer = context.packageManager.packageInstaller
        val params = PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL).apply {
            setAppPackageName(context.packageName); setSize(apk.length())
            setInstallReason(PackageManager.INSTALL_REASON_USER)
            // Android 12+ could otherwise let an app update itself without asking.
            if (Build.VERSION.SDK_INT >= 31) setRequireUserAction(PackageInstaller.SessionParams.USER_ACTION_REQUIRED)
        }
        val id = installer.createSession(params)
        try {
            installer.openSession(id).use { session ->
                // Hash the bytes Android actually receives, so a file changed after checking is refused.
                val written = session.openWrite("saiph.apk", 0, apk.length()).use { out ->
                    val digest = java.security.MessageDigest.getInstance("SHA-256")
                    apk.inputStream().use { input ->
                        val buffer = ByteArray(1 shl 16)
                        while (true) { val count = input.read(buffer); if (count < 0) break; digest.update(buffer, 0, count); out.write(buffer, 0, count) }
                    }
                    session.fsync(out)
                    digest.digest().joinToString("") { "%02x".format(it) }
                }
                if (written != release.sha256) throw UpdateRefused(UpdateRefused.Reason.HASH)
                // The system fills in the result, so the intent must be mutable; it is explicit to our receiver.
                val flags = PendingIntent.FLAG_UPDATE_CURRENT or (if (Build.VERSION.SDK_INT >= 31) PendingIntent.FLAG_MUTABLE else 0)
                val status = PendingIntent.getBroadcast(context, id, Intent(context, InstallResultReceiver::class.java).setPackage(context.packageName), flags)
                session.commit(status.intentSender)
            }
        } catch (failure: Exception) {
            runCatching { installer.abandonSession(id) }
            throw failure
        }
    }
}

/**
 * One update at a time for the whole app, so turning the screen or leaving the update screen
 * does not restart a download. The update screen draws [state]; the install result arrives
 * through [InstallResultReceiver].
 */
object UpdateController {
    sealed interface State {
        data object Idle : State
        data object Checking : State
        data class Current(val versionName: String) : State
        /** [resumable]: part of it is already downloaded. [ready]: downloaded and verified. */
        data class Available(val release: AppRelease, val place: String, val resumable: Boolean, val ready: Boolean) : State
        data class AskMetered(val release: AppRelease, val place: String) : State
        data class NeedsPermission(val release: AppRelease, val place: String) : State
        data class Downloading(val release: AppRelease, val place: String, val done: Long, val total: Long?) : State
        data class Verifying(val release: AppRelease) : State
        data class Confirming(val release: AppRelease, val place: String) : State
        /** [release]: Try again resumes it. [firebase]: Firebase App Tester can still be asked. */
        data class Failed(val message: String, val release: AppRelease?, val place: String?, val firebase: Boolean) : State
    }

    private val mutable = MutableStateFlow<State>(State.Idle)
    val state: StateFlow<State> = mutable
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var job: Job? = null

    fun directory(context: Context) = File(context.noBackupFilesDir, "updates")

    /**
     * Delete downloads this phone no longer needs: one for a build that is now installed (or
     * older), and the previous updater's cache file. A partial newer download stays to resume.
     */
    fun tidy(context: Context) {
        File(context.cacheDir, "orion-update.apk").delete()
        context.getSharedPreferences("orion", Context.MODE_PRIVATE).edit().remove("pending_android_release").apply()
        val prefs = context.getSharedPreferences("orion_updates", Context.MODE_PRIVATE)
        if (job?.isActive != true && prefs.getLong("download_code", 0) <= BuildConfig.VERSION_CODE) {
            directory(context).listFiles()?.forEach { it.delete() }
            prefs.edit().remove("download_code").apply()
        }
    }

    @Synchronized fun check(context: Context) {
        if (job?.isActive == true) return
        val app = context.applicationContext
        job = scope.launch {
            mutable.value = State.Checking
            mutable.value = try { checked(app) }
                catch (cancelled: CancellationException) { throw cancelled }
                catch (unavailable: UpdateUnavailable) { State.Failed(unavailable.message!!, null, null, BuildConfig.HAS_APP_DISTRIBUTION) }
                catch (refused: UpdateRefused) { State.Failed(refused.message!!, null, null, BuildConfig.HAS_APP_DISTRIBUTION) }
                catch (_: Exception) { State.Failed(offlineOr(app, "Couldn't reach the update service. Try again in a moment."), null, null, BuildConfig.HAS_APP_DISTRIBUTION) }
        }
    }

    private suspend fun checked(context: Context): State {
        if (!online(context)) return State.Failed(OFFLINE, null, null, false)
        val source = UpdateSources.select(context)
            ?: return State.Failed(if (BuildConfig.HAS_APP_DISTRIBUTION) "Updates for this copy of Saiph come from Firebase App Tester."
                else "This copy of Saiph has no update source. Get the latest app from usesaiph.com/downloads.html.", null, null, BuildConfig.HAS_APP_DISTRIBUTION)
        val release = source.latest() ?: return State.Current(BuildConfig.VERSION_NAME)
        return when (UpdatePolicy.decide(BuildConfig.VERSION_CODE.toLong(), release, Build.VERSION.SDK_INT)) {
            UpdatePolicy.Decision.CURRENT -> State.Current(BuildConfig.VERSION_NAME)
            UpdatePolicy.Decision.DOWNGRADE -> State.Failed(UpdateRefused.Reason.DOWNGRADE.message, null, null, false)
            UpdatePolicy.Decision.INCOMPATIBLE -> State.Failed(UpdateRefused.Reason.INCOMPATIBLE.message, null, null, false)
            UpdatePolicy.Decision.NEWER -> available(context, release, source.place)
        }
    }

    private fun available(context: Context, release: AppRelease, place: String): State.Available {
        val download = ResumableDownload(directory(context), release)
        return State.Available(release, place, download.partial.length() > 0, download.finished.exists())
    }

    /**
     * Download (or resume), verify and hand to Android. On a metered network this stops at
     * [State.AskMetered] unless [allowMetered]; without the install permission it stops at
     * [State.NeedsPermission] with the verified file kept.
     */
    @Synchronized fun update(context: Context, release: AppRelease, place: String, allowMetered: Boolean = false) {
        if (job?.isActive == true) return
        val app = context.applicationContext
        job = scope.launch {
            val download = ResumableDownload(directory(app), release)
            app.getSharedPreferences("orion_updates", Context.MODE_PRIVATE).edit().putLong("download_code", release.versionCode).apply()
            try {
                if (!download.finished.exists()) {
                    if (!online(app)) { mutable.value = State.Failed(OFFLINE, release, place, false); return@launch }
                    if (metered(app) && !allowMetered) { mutable.value = State.AskMetered(release, place); return@launch }
                }
                val source = UpdateSources.select(app) ?: throw UpdateUnavailable("This phone no longer has an update source.")
                val opener = if (download.finished.exists()) ResumableDownload.Opener { throw IOException("Already downloaded") } else source.opener()
                val running = coroutineContext
                mutable.value = State.Downloading(release, place, download.partial.length(), release.bytes)
                val apk = download.run(opener) { done, total ->
                    mutable.value = State.Downloading(release, place, done, total); running.isActive
                }
                mutable.value = State.Verifying(release)
                try { UpdateVerifier.check(PackageFactsReader.archive(app, apk), PackageFactsReader.installed(app), release) }
                catch (refused: UpdateRefused) { apk.delete(); throw refused }
                if (!UpdateInstaller.canInstall(app)) { mutable.value = State.NeedsPermission(release, place); return@launch }
                mutable.value = State.Confirming(release, place)
                UpdateInstaller.install(app, apk, release)
            } catch (cancelled: CancellationException) {
                mutable.value = available(app, release, place); throw cancelled
            } catch (refused: UpdateRefused) {
                mutable.value = State.Failed(refused.message!!, null, null, false)
            } catch (unavailable: UpdateUnavailable) {
                mutable.value = State.Failed(unavailable.message!!, release, place, false)
            } catch (_: Exception) {
                // A paused download stops with an IOException from its progress callback.
                mutable.value = if (!isActive) available(app, release, place)
                    else State.Failed(offlineOr(app, "The download stopped. Try again to continue where it left off."), release, place, false)
            }
        }
    }

    @Synchronized fun pause() { job?.cancel() }

    /** From [InstallResultReceiver]: Android's prompt was dismissed or the install failed. */
    fun installFinished(context: Context, message: String?) {
        val confirming = mutable.value as? State.Confirming
        mutable.value = when {
            confirming == null -> if (message == null) State.Idle else State.Failed(message, null, null, false)
            message == null -> available(context, confirming.release, confirming.place)
            else -> State.Failed(message, confirming.release, confirming.place, false)
        }
    }

    private const val OFFLINE = "You're offline. Connect to the internet, then try again."
    private fun offlineOr(context: Context, message: String) = if (online(context)) message else OFFLINE

    private fun capabilities(context: Context): NetworkCapabilities? {
        val manager = context.getSystemService(ConnectivityManager::class.java)
        return manager.activeNetwork?.let(manager::getNetworkCapabilities)
    }
    fun online(context: Context) = capabilities(context)?.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) == true
    fun metered(context: Context) = context.getSystemService(ConnectivityManager::class.java).isActiveNetworkMetered
}

class InstallResultReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        when (intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE)) {
            PackageInstaller.STATUS_PENDING_USER_ACTION -> {
                val confirm = if (Build.VERSION.SDK_INT >= 33) intent.getParcelableExtra(Intent.EXTRA_INTENT, Intent::class.java)
                    else @Suppress("DEPRECATION") intent.getParcelableExtra(Intent.EXTRA_INTENT)
                confirm?.let { context.startActivity(it.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
            }
            PackageInstaller.STATUS_SUCCESS -> UpdateController.directory(context).listFiles()?.forEach { it.delete() }
            // Declined at Android's prompt: keep the verified file so Install works again without downloading.
            PackageInstaller.STATUS_FAILURE_ABORTED -> UpdateController.installFinished(context, null)
            else -> UpdateController.installFinished(context, "Android didn't install the update" +
                (intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE)?.take(200)?.let { ": $it" } ?: "."))
        }
    }
}

/** The automatic check: a notification when a newer build is published. It never downloads or installs. */
object UpdateNotices {
    private const val PREFS = "orion_updates"
    private const val CHANNEL = "orion_update"
    private const val ID = 43

    fun automatic(context: Context) = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getBoolean("auto_check", true)

    fun setAutomatic(context: Context, on: Boolean) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putBoolean("auto_check", on).apply()
        UpdateCheckWorker.schedule(context)
    }

    suspend fun checkQuietly(context: Context) {
        if (!automatic(context)) return
        val source = UpdateSources.select(context) ?: return
        val release = try { source.latest() } catch (cancelled: CancellationException) { throw cancelled } catch (_: Exception) { return } ?: return
        if (UpdatePolicy.decide(BuildConfig.VERSION_CODE.toLong(), release, Build.VERSION.SDK_INT) != UpdatePolicy.Decision.NEWER) return
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        if (prefs.getLong("notified_code", 0) == release.versionCode) return
        val manager = context.getSystemService(NotificationManager::class.java)
        if (!manager.areNotificationsEnabled() || (Build.VERSION.SDK_INT >= 33 &&
                ActivityCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED)) return
        manager.createNotificationChannel(NotificationChannel(CHANNEL, "Saiph updates", NotificationManager.IMPORTANCE_DEFAULT))
        val open = PendingIntent.getActivity(context, ID, Intent(context, UpdateActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        manager.notify(ID, NotificationCompat.Builder(context, CHANNEL).setSmallIcon(android.R.drawable.stat_sys_download_done)
            .setContentTitle("Saiph ${release.versionName} is available")
            .setContentText("Tap to see what's new. Android asks before installing.")
            .setContentIntent(open).setAutoCancel(true).setOnlyAlertOnce(true).build())
        prefs.edit().putLong("notified_code", release.versionCode).apply()
    }
}

class UpdateCheckWorker(context: Context, parameters: WorkerParameters) : CoroutineWorker(context, parameters) {
    override suspend fun doWork(): Result {
        UpdateNotices.checkQuietly(applicationContext)
        return Result.success()
    }

    companion object {
        private const val WORK = "saiph-update-check"
        fun schedule(context: Context) {
            val manager = WorkManager.getInstance(context)
            if (!UpdateNotices.automatic(context)) { manager.cancelUniqueWork(WORK); return }
            val request = PeriodicWorkRequestBuilder<UpdateCheckWorker>(24, TimeUnit.HOURS, 6, TimeUnit.HOURS)
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()).build()
            manager.enqueueUniquePeriodicWork(WORK, ExistingPeriodicWorkPolicy.KEEP, request)
        }
    }
}
