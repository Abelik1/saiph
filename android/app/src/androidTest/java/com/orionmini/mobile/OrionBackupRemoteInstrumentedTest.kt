package com.orionmini.mobile

import android.content.ContentValues
import android.provider.MediaStore
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.work.ListenableWorker
import androidx.work.testing.TestListenableWorkerBuilder
import io.github.resticdroid.restic.*
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith
import sefirah.network.orion.Api
import java.io.File
import java.security.MessageDigest
import java.util.UUID

/** Opt-in live Pi proof. Root supplies a one-time code privately; no A55 access. */
@RunWith(AndroidJUnit4::class)
class OrionBackupRemoteInstrumentedTest {
    private enum class Phase {
        PAIRING_FILE, PAIRING_REQUEST, MEDIA_CREATE, WORKER_BUILD, WORKER_RUN,
        WORKER_COMPLETE, BOOTSTRAP, TARGET_VALIDATION, RESTORE, RESTORED_FILE,
        HASH_CHECK, CREDENTIAL_PERSISTENCE_CHECK
    }

    @Test fun pairedWorkerSnapshotsAndRestoresFromPi() = runBlocking {
        assumeTrue(InstrumentationRegistry.getArguments().getString("approvedremote") == "true")
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val pairing = File(context.cacheDir, "orion-backup-remote-pairing.json")
        val preferences = context.getSharedPreferences("orion_backup", 0)
        val previousFolders = preferences.getStringSet("folders", emptySet()).orEmpty().toSet()
        val previousEnabled = preferences.getBoolean("enabled", true)
        val name = "orion-remote-proof-${UUID.randomUUID()}.bin"
        var received: android.net.Uri? = null
        val restore = File(context.cacheDir, "orion-remote-restore-${UUID.randomUUID()}")
        var phase = Phase.PAIRING_FILE
        try {
            check(pairing.isFile)
            val authorization = JSONObject(pairing.readText())
            pairing.delete()
            phase = Phase.PAIRING_REQUEST
            Api.pair(context, authorization.getString("hub"), authorization.getString("code"), "Orion backup emulator proof")
            preferences.edit().putStringSet("folders", emptySet()).putBoolean("enabled", true).commit()
            val bytes = ByteArray(262151) { (it * 29).toByte() }
            val values = ContentValues().apply {
                put(MediaStore.Downloads.DISPLAY_NAME, name)
                put(MediaStore.Downloads.MIME_TYPE, "application/octet-stream")
                put(MediaStore.Downloads.RELATIVE_PATH, "Download/Orion")
                put(MediaStore.Downloads.IS_PENDING, 1)
            }
            phase = Phase.MEDIA_CREATE
            received = context.contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)!!
            context.contentResolver.openOutputStream(received)!!.use { it.write(bytes) }
            values.clear(); values.put(MediaStore.Downloads.IS_PENDING, 0)
            context.contentResolver.update(received, values, null, null)
            var successful = false
            repeat(8) {
                if (!successful) {
                    phase = Phase.WORKER_BUILD
                    val worker = TestListenableWorkerBuilder<OrionBackupWorker>(context).build()
                    phase = Phase.WORKER_RUN
                    successful = worker.doWork() == ListenableWorker.Result.success()
                    if (!successful) delay(10000) // Standard rest-server authentication reload.
                }
            }
            phase = Phase.WORKER_COMPLETE
            check(successful && preferences.getString("state", "") == "ready")
            phase = Phase.BOOTSTRAP
            val target = JSONObject(Api.request(context, "/v1/link/backups/bootstrap", "POST", JSONObject()))
                .getJSONArray("targets").getJSONObject(0)
            phase = Phase.TARGET_VALIDATION
            val repository = OrionBackupWorker.parseTarget(target)
            val restic = Restic.from(context)
            phase = Phase.RESTORE
            check(OrionBackupWorker.run(restic, repository,
                ResticCommand.restore("latest", restore.absolutePath)) == ResticExit.OK)
            phase = Phase.RESTORED_FILE
            val recovered = restore.walkTopDown().single { it.isFile && it.name.startsWith(name) }
            val expected = MessageDigest.getInstance("SHA-256").digest(bytes)
            val actual = MessageDigest.getInstance("SHA-256")
            recovered.inputStream().use { input -> val buffer = ByteArray(8192); while (true) {
                val count = input.read(buffer); if (count < 0) break; actual.update(buffer, 0, count)
            } }
            phase = Phase.HASH_CHECK
            check(expected.contentEquals(actual.digest()))
            // No bootstrap credentials may enter any persistent Android preference file.
            val privatePreferences = File(context.applicationInfo.dataDir, "shared_prefs")
            val credentials = listOf(repository.password) + repository.env.values
            phase = Phase.CREDENTIAL_PERSISTENCE_CHECK
            for (file in privatePreferences.listFiles().orEmpty().filter { it.isFile }) {
                val content = file.readText()
                check(credentials.none { it in content })
            }
        } catch (failure: Exception) {
            // Do not attach a process diagnostic, path, pairing code or backend response to JUnit.
            throw AssertionError("Remote Android backup proof failed: phase=${phase.name}; exception=${failure.javaClass.simpleName}.")
        } finally {
            pairing.delete()
            received?.let { context.contentResolver.delete(it, null, null) }
            restore.deleteRecursively()
            preferences.edit().putStringSet("folders", previousFolders).putBoolean("enabled", previousEnabled).commit()
            runCatching { OrionBackupSources(context).stage() }
        }
    }
}
