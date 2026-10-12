package com.orionmini.mobile

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.pm.ServiceInfo
import android.net.Uri
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.work.*
import io.github.resticdroid.restic.*
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import org.json.JSONObject
import sefirah.network.orion.Api
import sefirah.network.orion.MeshOrigin
import java.util.concurrent.TimeUnit

/** Upstream restic runs inside Orion's UID; only explicitly accessible content is staged. */
class OrionBackupWorker(context: Context, parameters: WorkerParameters) : CoroutineWorker(context, parameters) {
    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        val context = applicationContext
        val preferences = context.getSharedPreferences("orion_backup", Context.MODE_PRIVATE)
        if (!preferences.getBoolean("enabled", true)) return@withContext Result.success()
        if (!context.getSharedPreferences("orion", Context.MODE_PRIVATE).contains("device_id")) return@withContext Result.retry()
        try {
            setForeground(foreground(context))
            preferences.edit().putString("state", "running").apply()
            withTimeout(TimeUnit.HOURS.toMillis(4)) {
                val restic = Restic.from(context)
                check(restic.isAvailable())
                // Never persist, publish, display or log the bootstrap's credentials.
                val targets = JSONObject(Api.request(context, "/v1/link/backups/bootstrap", "POST", JSONObject())).getJSONArray("targets")
                check(targets.length() in 1..4)
                val sources = OrionBackupSources(context).stage()
                var finalSummary: ResticEvent.Summary? = null
                for (index in 0 until targets.length()) {
                    val repository = parseTarget(targets.getJSONObject(index))
                    var exit = run(restic, repository, ResticCommand.catConfig())
                    if (exit == ResticExit.REPOSITORY_NOT_FOUND) exit = run(restic, repository, ResticCommand.init())
                    check(exit == ResticExit.OK)
                    exit = run(restic, repository, ResticCommand.backup(
                        listOf(sources.absolutePath), tags = listOf("orion-android"), host = "orion-android"
                    )) { summary -> finalSummary = summary }
                    // Upstream considers exit 3 usable; Orion must report unreadable content as incomplete.
                    check(exit == ResticExit.OK && finalSummary?.snapshotId != null)
                }
                preferences.edit().putString("state", "ready").putLong("last_success", System.currentTimeMillis())
                    .putLong("files", finalSummary?.totalFilesProcessed ?: 0)
                    .putLong("bytes", finalSummary?.totalBytesProcessed ?: 0).apply()
            }
            Result.success()
        } catch (_: TimeoutCancellationException) {
            preferences.edit().putString("state", "waiting").apply()
            Result.retry()
        } catch (cancelled: CancellationException) {
            preferences.edit().putString("state", "waiting").apply()
            throw cancelled
        } catch (_: OrionBackupSources.PermissionNeeded) {
            preferences.edit().putString("state", "permission").apply()
            Result.retry()
        } catch (_: OrionBackupSources.StorageNeeded) {
            preferences.edit().putString("state", "storage").apply()
            Result.retry()
        } catch (_: Exception) {
            // Fixed metadata only: native diagnostics can contain paths, server credentials or bodies.
            preferences.edit().putString("state", "waiting").apply()
            Result.retry()
        }
    }

    companion object {
        private const val WORK = "orion-daily-backup"
        fun schedule(context: Context) {
            val preferences = context.getSharedPreferences("orion_backup", Context.MODE_PRIVATE)
            val manager = WorkManager.getInstance(context)
            if (!preferences.getBoolean("enabled", true)) { manager.cancelUniqueWork(WORK); return }
            val network = if (preferences.getBoolean("mobile_data", false)) NetworkType.CONNECTED else NetworkType.UNMETERED
            val request = PeriodicWorkRequestBuilder<OrionBackupWorker>(24, TimeUnit.HOURS, 2, TimeUnit.HOURS)
                .setConstraints(Constraints.Builder().setRequiresCharging(true).setRequiresStorageNotLow(true).setRequiredNetworkType(network).build())
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 15, TimeUnit.MINUTES)
                .build()
            manager.enqueueUniquePeriodicWork(WORK, ExistingPeriodicWorkPolicy.UPDATE, request)
        }

        internal fun parseTarget(target: JSONObject): ResticRepository {
            val location = target.getString("repository")
            require(location.startsWith("rest:"))
            val uri = Uri.parse(location.removePrefix("rest:"))
            val host = uri.host.orEmpty()
            require(uri.scheme in listOf("http", "https") && MeshOrigin.isAddress(host))
            require(uri.userInfo == null && uri.query == null && uri.fragment == null && !uri.path.orEmpty().contains(".."))
            val credentials = target.getJSONObject("backend_environment")
            val allowed = listOf("RESTIC_REST_USERNAME", "RESTIC_REST_PASSWORD")
            require(credentials.keys().asSequence().toSet() == allowed.toSet())
            val environment = allowed.associateWith { credentials.getString(it).also { value -> require(value.length in 1..1024 && '\u0000' !in value) } }
            val password = target.getString("repository_password").also { require(it.length in 16..1024 && '\u0000' !in it) }
            return ResticRepository(location, password, environment)
        }

        internal suspend fun run(restic: Restic, repository: ResticRepository, command: ResticCommand,
                                 summary: (ResticEvent.Summary) -> Unit = {}): Int {
            var exit = -1
            restic.stream(repository, command).collect { event ->
                when (event) {
                    is ResticEvent.Finished -> exit = event.exitCode
                    is ResticEvent.Summary -> summary(event)
                    else -> Unit // Drop paths, diagnostics, bodies and raw JSON without logging.
                }
            }
            return exit
        }

        private fun foreground(context: Context): ForegroundInfo {
            val manager = context.getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(NotificationChannel("orion_backup", "Automatic backups", NotificationManager.IMPORTANCE_LOW))
            val notification = NotificationCompat.Builder(context, "orion_backup")
                .setSmallIcon(android.R.drawable.stat_notify_sync).setContentTitle("Saiph backup")
                .setContentText("Protecting your selected files automatically.").setOngoing(true).setSilent(true).build()
            return if (Build.VERSION.SDK_INT >= 29) ForegroundInfo(7312, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
            else ForegroundInfo(7312, notification)
        }
    }
}
