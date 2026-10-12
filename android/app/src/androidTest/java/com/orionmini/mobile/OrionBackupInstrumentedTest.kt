package com.orionmini.mobile

import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import android.content.ContentValues
import android.os.Build
import android.provider.MediaStore
import io.github.resticdroid.restic.*
import kotlinx.coroutines.runBlocking
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.security.MessageDigest
import java.util.UUID

/** Executes the APK's extracted executable as Orion's UID, not as adb shell. */
@RunWith(AndroidJUnit4::class)
class OrionBackupInstrumentedTest {
    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext

    @Test fun bundledNativeVersion() = runBlocking {
        val restic = Restic.from(context)
        assertTrue("extracted APK native executable", restic.isAvailable())
        val result = restic.execute(null, ResticCommand.version())
        assertEquals(0, result.exitCode)
        assertTrue(result.stdout.startsWith("restic 0.19.1"))
    }

    @Test fun localSnapshotRestoresByteHash() = runBlocking {
        val root = File(context.cacheDir, "backup-proof-${UUID.randomUUID()}").apply { mkdirs() }
        try {
            val original = File(root, "source/proof.bin").apply {
                parentFile!!.mkdirs(); writeBytes(ByteArray(196613) { (it * 31).toByte() })
            }
            val repository = ResticRepository(File(root, "repository").absolutePath, "test-only-${UUID.randomUUID()}")
            val restic = Restic.from(context)
            assertEquals(0, OrionBackupWorker.run(restic, repository, ResticCommand.init()))
            var snapshot: String? = null
            assertEquals(0, OrionBackupWorker.run(restic, repository,
                ResticCommand.backup(listOf(original.parentFile!!.absolutePath), tags = listOf("orion-proof"))) { snapshot = it.snapshotId })
            assertNotNull(snapshot)
            val restore = File(root, "restore")
            assertEquals(0, OrionBackupWorker.run(restic, repository, ResticCommand.restore(snapshot!!, restore.absolutePath)))
            val recovered = restore.walkTopDown().single { it.isFile && it.name == "proof.bin" }
            fun hash(file: File): String {
                val digest = MessageDigest.getInstance("SHA-256")
                file.inputStream().use { input -> val buffer = ByteArray(8192); while (true) {
                    val count = input.read(buffer); if (count < 0) break; digest.update(buffer, 0, count)
                } }
                return digest.digest().joinToString("") { "%02x".format(it) }
            }
            assertEquals(hash(original), hash(recovered))
        } finally { root.deleteRecursively() }
    }

    @Test fun bootstrapCannotExpandToPublicHostsOrProcessEnvironment() {
        fun target(repository: String) = JSONObject().put("repository", repository)
            .put("repository_password", "test-only-long-password")
            .put("backend_environment", JSONObject().put("RESTIC_REST_USERNAME", "test")
                .put("RESTIC_REST_PASSWORD", "test-only"))
        assertEquals("rest:http://100.64.0.2:8768/orion-test/", OrionBackupWorker.parseTarget(target("rest:http://100.64.0.2:8768/orion-test/")).uri)
        for (location in listOf("rest:https://example.com/repository/", "rest:http://100.64.0.2/../escape", "rest:http://user:password@100.64.0.2/", "sftp:example.com:repository")) {
            assertTrue(runCatching { OrionBackupWorker.parseTarget(target(location)) }.isFailure)
        }
        val injected = target("rest:http://100.64.0.2:8768/orion-test/")
        injected.getJSONObject("backend_environment").put("LD_PRELOAD", "/private/library")
        assertTrue(runCatching { OrionBackupWorker.parseTarget(injected) }.isFailure)
        assertFalse(OrionBackupSources.safeName("../../private/file").contains('/'))
    }

    @Test fun ownedReceivedContentOnlyAndLostGrantNeverCompletes() = runBlocking {
        if (Build.VERSION.SDK_INT < 29) return@runBlocking
        val preferences = context.getSharedPreferences("orion_backup", 0)
        val saved = preferences.getStringSet("folders", emptySet()).orEmpty().toSet()
        val name = "orion-backup-proof-${UUID.randomUUID()}.bin"
        val values = ContentValues().apply {
            put(MediaStore.Downloads.DISPLAY_NAME, name)
            put(MediaStore.Downloads.MIME_TYPE, "application/octet-stream")
            put(MediaStore.Downloads.RELATIVE_PATH, "Download/Orion")
            put(MediaStore.Downloads.IS_PENDING, 1)
        }
        val uri = context.contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)!!
        val secret = File(context.filesDir, "backup-proof-private-credential")
        val bytes = ByteArray(1027) { (it * 17).toByte() }
        try {
            preferences.edit().putStringSet("folders", emptySet()).commit()
            secret.writeText("synthetic-credential-excluded")
            context.contentResolver.openOutputStream(uri)!!.use { it.write(bytes) }
            values.clear(); values.put(MediaStore.Downloads.IS_PENDING, 0)
            context.contentResolver.update(uri, values, null, null)
            val root = OrionBackupSources(context).stage()
            val staged = root.walkTopDown().single { it.isFile && it.name.startsWith(name) }
            assertArrayEquals(bytes, staged.readBytes())
            assertFalse(root.walkTopDown().any { it.isFile && it.name.contains(secret.name) })
            preferences.edit().putStringSet("folders", setOf("content://invalid.orion.provider/tree/missing")).commit()
            assertTrue(runCatching { OrionBackupSources(context).stage() }.exceptionOrNull() is OrionBackupSources.PermissionNeeded)
        } finally {
            context.contentResolver.delete(uri, null, null)
            secret.delete()
            preferences.edit().putStringSet("folders", saved).commit()
            // Return the private mirror to the owner's selected scope after the synthetic proof.
            runCatching { OrionBackupSources(context).stage() }
        }
    }
}
