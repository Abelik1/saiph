// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import com.castle.sefirah.BuildConfig
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.ByteArrayInputStream
import java.io.File
import java.io.IOException
import java.security.MessageDigest
import kotlin.random.Random

/** Synthetic fixtures only: made-up builds, bytes and certificates. */
class AppUpdateTest {
    @get:Rule val folder = TemporaryFolder()

    private fun sha(bytes: ByteArray) = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
    private val apk = Random(7).nextBytes(300_000)
    private val apkHash = sha(apk)

    private fun hosted(vararg changes: Pair<String, String?>): String {
        val fields = linkedMapOf("schema" to "1", "package" to "\"com.orionmini.mobile\"", "version_code" to "3575000",
            "version_name" to "\"0.9.8\"", "sha256" to "\"$apkHash\"", "bytes" to "${apk.size}", "min_sdk" to "26",
            "notes" to "\"Faster photo sync.\\nFixes the widget.\"")
        changes.forEach { (key, value) -> if (value == null) fields.remove(key) else fields[key] = value }
        return fields.entries.joinToString(",", "{", "}") { "\"${it.key}\":${it.value}" }
    }
    private fun refused(raw: String) = refused(raw.toByteArray())
    private fun refused(raw: ByteArray) {
        val failure = runCatching { UpdateManifest.hosted(raw) }.exceptionOrNull()
        assertTrue("accepted: ${String(raw)}", failure is UpdateRefused && failure.reason == UpdateRefused.Reason.MANIFEST)
    }

    // --- Manifest: the Saiph account schema ---

    @Test fun validHostedManifestParses() {
        val release = UpdateManifest.hosted(hosted().toByteArray())
        assertEquals(3575000L, release.versionCode)
        assertEquals("0.9.8", release.versionName)
        assertEquals(apkHash, release.sha256)
        assertEquals(apk.size.toLong(), release.bytes)
        assertEquals(26, release.minSdk)
        assertEquals("Faster photo sync.\nFixes the widget.", release.notes)
        assertEquals("0.9.8 (build 3575000)", release.label)
        assertEquals("0.9.8-beta.2", UpdateManifest.hosted(hosted("version_name" to "\"0.9.8-beta.2\"").toByteArray()).versionName)
    }

    @Test fun everyKeyIsRequiredAndNoOtherIsAllowed() {
        for (key in listOf("schema", "package", "version_code", "version_name", "sha256", "bytes", "min_sdk", "notes"))
            refused(hosted(key to null))
        refused(hosted("apk_url" to "\"https://elsewhere.invalid/saiph.apk\""))
    }

    @Test fun wrongSchemaOrPackageIsRefused() {
        refused(hosted("schema" to "2"))
        refused(hosted("schema" to "\"1\""))
        refused(hosted("package" to "\"com.example.other\""))
    }

    @Test fun versionCodeMustBeAPositiveAndroidVersionCode() {
        for (value in listOf("0", "-1", "2100000001", "3575000.0", "3.575e6", "\"3575000\"", "true", "null"))
            refused(hosted("version_code" to value))
        assertEquals(2_100_000_000L, UpdateManifest.hosted(hosted("version_code" to "2100000000").toByteArray()).versionCode)
    }

    @Test fun hashesMustBeLowercaseSha256Hex() {
        refused(hosted("sha256" to "\"${apkHash.uppercase()}\""))
        refused(hosted("sha256" to "\"${apkHash.dropLast(1)}\""))
        refused(hosted("sha256" to "\"${apkHash.dropLast(1)}g\""))
    }

    @Test fun sizesNamesAndSdkAreBounded() {
        refused(hosted("bytes" to "0"))
        refused(hosted("bytes" to "200000001"))
        refused(hosted("min_sdk" to "20"))
        refused(hosted("min_sdk" to "100"))
        for (name in listOf("\"\"", "\"latest\"", "\"0.9\"", "\"0.9.8 \"", "\"0.9.8-\"", "\"0.9.8-beta 2\"", "\"0.9.8/../x\""))
            refused(hosted("version_name" to name))
    }

    @Test fun notesRefuseControlAndDirectionCharacters() {
        refused(hosted("notes" to "\"a\\u0007b\""))
        refused(hosted("notes" to "\"Update \\u202eexe.kpa\""))
        refused(hosted("notes" to "\"${"x".repeat(4001)}\""))
        assertEquals("", UpdateManifest.hosted(hosted("notes" to "\"  \"").toByteArray()).notes)
    }

    @Test fun repeatedKeysAreRefusedSoOneValueCannotBeShownAndAnotherUsed() {
        val doubled = hosted().dropLast(1) + ",\"version_code\":9999999}"
        refused(doubled)
        // A colon inside a string value is not a key.
        assertEquals("Fixes: sync", UpdateManifest.hosted(hosted("notes" to "\"Fixes: sync\"").toByteArray()).notes)
    }

    @Test fun malformedOrOversizedDocumentsAreRefused() {
        refused("")
        refused("[]")
        refused(hosted() + "x")
        refused(hosted("notes" to "{\"a\":1}"))
        refused(byteArrayOf('{'.code.toByte(), 0xC3.toByte(), 0x28, '}'.code.toByte()))
        refused(hosted("notes" to "\"${"y".repeat(17_000)}\""))
    }

    // --- Manifest: a self-hosted Hub ---

    @Test fun hubReleaseParsesWithOptionalSize() {
        val raw = """{"release":{"version_code":3575000,"version_name":"0.9.8","sha256":"$apkHash","size":300000,"published_at":"2026-10-18T10:00:00Z"}}"""
        val release = UpdateManifest.hub(raw.toByteArray())!!
        assertEquals(3575000L, release.versionCode); assertEquals(300000L, release.bytes); assertEquals("", release.notes)
        assertNull(UpdateManifest.hub("""{"release":{"version_code":2,"version_name":"x","sha256":"$apkHash"}}""".toByteArray())!!.bytes)
        assertNull(UpdateManifest.hub("""{"release":null}""".toByteArray()))
    }

    @Test fun hubReleaseIsStrictToo() {
        for (raw in listOf("""{}""", """{"release":null,"x":1}""", """{"release":{"version_code":2,"version_name":"x"}}""",
                """{"release":{"version_code":2,"version_name":"x","sha256":"$apkHash","url":"http://x"}}""",
                """{"release":{"version_code":0,"version_name":"x","sha256":"$apkHash"}}""",
                """{"release":{"version_code":2,"version_name":"a b","sha256":"$apkHash"}}"""))
            assertTrue(raw, runCatching { UpdateManifest.hub(raw.toByteArray()) }.exceptionOrNull() is UpdateRefused)
    }

    // --- Version policy ---

    private fun release(code: Long, minSdk: Int? = 26, bytes: Long? = apk.size.toLong(), hash: String = apkHash) =
        AppRelease(code, "0.9.8", hash, bytes, "", minSdk)

    @Test fun onlyAStrictlyNewerVersionCodeIsOffered() {
        assertEquals(UpdatePolicy.Decision.NEWER, UpdatePolicy.decide(3574000, release(3575000), 34))
        assertEquals(UpdatePolicy.Decision.CURRENT, UpdatePolicy.decide(3575000, release(3575000), 34))
        assertEquals(UpdatePolicy.Decision.DOWNGRADE, UpdatePolicy.decide(3576000, release(3575000), 34))
        assertEquals(UpdatePolicy.Decision.INCOMPATIBLE, UpdatePolicy.decide(3574000, release(3575000, minSdk = 35), 34))
        assertEquals(UpdatePolicy.Decision.NEWER, UpdatePolicy.decide(3574000, release(3575000, minSdk = null), 26))
        // An older build is refused even when it would also be incompatible.
        assertEquals(UpdatePolicy.Decision.DOWNGRADE, UpdatePolicy.decide(3576000, release(3575000, minSdk = 99), 26))
    }

    @Test fun sizesReadForPeople() {
        assertEquals("58 MB", UpdatePolicy.size(57_872_502))
        assertEquals("300 kB", UpdatePolicy.size(300_000))
        assertEquals("1 kB", UpdatePolicy.size(10))
        assertEquals("size unknown", UpdatePolicy.size(null))
    }

    // --- Hash and signer verification ---

    @Test fun sha256MatchesKnownVectors() {
        assertEquals("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", UpdateVerifier.sha256(ByteArrayInputStream("abc".toByteArray())))
        val file = folder.newFile().apply { writeBytes(apk) }
        assertEquals(apkHash, UpdateVerifier.sha256(file))
        assertEquals(sha("synthetic certificate".toByteArray()), UpdateVerifier.certificate("synthetic certificate".toByteArray()))
    }

    private val publisher = UpdateVerifier.certificate("synthetic publisher certificate".toByteArray())
    private val stranger = UpdateVerifier.certificate("synthetic other certificate".toByteArray())
    private val installed = PackageFacts("com.orionmini.mobile", 3574000, setOf(publisher))

    private fun reason(archive: PackageFacts?, from: PackageFacts = installed, published: AppRelease = release(3575000)) =
        (runCatching { UpdateVerifier.check(archive, from, published) }.exceptionOrNull() as? UpdateRefused)?.reason

    @Test fun matchingPackageVersionAndSignerIsAccepted() {
        assertNull(reason(PackageFacts("com.orionmini.mobile", 3575000, setOf(publisher))))
        val pair = setOf(publisher, stranger)
        assertNull(reason(PackageFacts("com.orionmini.mobile", 3575000, pair), installed.copy(signers = pair)))
    }

    @Test fun anotherSignerIsRefused() {
        assertEquals(UpdateRefused.Reason.SIGNER, reason(PackageFacts("com.orionmini.mobile", 3575000, setOf(stranger))))
        assertEquals(UpdateRefused.Reason.SIGNER, reason(PackageFacts("com.orionmini.mobile", 3575000, emptySet())))
        // An extra or a missing co-signer is still a different signer set.
        assertEquals(UpdateRefused.Reason.SIGNER, reason(PackageFacts("com.orionmini.mobile", 3575000, setOf(publisher, stranger))))
        // Unknown installed signers never match anything, not even an unsigned archive.
        assertEquals(UpdateRefused.Reason.SIGNER, reason(PackageFacts("com.orionmini.mobile", 3575000, emptySet()), installed.copy(signers = emptySet())))
    }

    @Test fun wrongPackageVersionOrUnreadableArchiveIsRefused() {
        assertEquals(UpdateRefused.Reason.UNREADABLE, reason(null))
        assertEquals(UpdateRefused.Reason.PACKAGE, reason(PackageFacts("com.example.other", 3575000, setOf(publisher))))
        assertEquals(UpdateRefused.Reason.VERSION, reason(PackageFacts("com.orionmini.mobile", 3575001, setOf(publisher))))
        // A manifest claiming a newer build cannot carry an older APK.
        assertEquals(UpdateRefused.Reason.DOWNGRADE, reason(PackageFacts("com.orionmini.mobile", 3570000, setOf(publisher)), published = release(3570000)))
        assertEquals(UpdateRefused.Reason.DOWNGRADE, reason(PackageFacts("com.orionmini.mobile", 3574000, setOf(publisher)), published = release(3574000)))
    }

    // --- Resumable download ---

    private class FakeServer(val body: ByteArray, var ranges: Boolean = true, var answer: ((Long) -> ResumableDownload.Answer)? = null) {
        val offsets = mutableListOf<Long>()
        fun opener() = ResumableDownload.Opener { offset ->
            offsets += offset
            answer?.invoke(offset) ?: if (offset > 0 && ranges)
                ResumableDownload.Answer(206, "bytes $offset-${body.size - 1}/${body.size}", ByteArrayInputStream(body, offset.toInt(), body.size - offset.toInt()))
            else ResumableDownload.Answer(200, null, ByteArrayInputStream(body))
        }
    }

    private fun directory() = File(folder.root, "updates")
    private fun download(published: AppRelease = release(3575000)) = ResumableDownload(directory(), published)
    private val always: (Long, Long?) -> Boolean = { _, _ -> true }

    @Test fun freshDownloadIsVerifiedAndNamedByItsHash() {
        val server = FakeServer(apk)
        val updates = mutableListOf<Long>()
        val file = download().run(server.opener()) { done, total -> assertEquals(apk.size.toLong(), total); updates += done; true }
        assertArrayEquals(apk, file.readBytes())
        assertEquals("$apkHash.apk", file.name)
        assertEquals(listOf(0L), server.offsets)
        assertEquals(apk.size.toLong(), updates.last())
        assertFalse(download().partial.exists())
    }

    @Test fun pausedDownloadKeepsItsPartAndResumesWithARange() {
        val server = FakeServer(apk)
        val paused = runCatching { download().run(server.opener()) { done, _ -> done < 100_000 } }.exceptionOrNull()
        assertTrue(paused is IOException && paused !is UpdateRefused)
        val kept = download().partial.length()
        assertTrue(kept in 100_000 until apk.size)
        val file = download().run(server.opener(), always)
        assertArrayEquals(apk, file.readBytes())
        assertEquals(listOf(0L, kept), server.offsets)
    }

    @Test fun serverIgnoringTheRangeRestartsFromTheBeginning() {
        download().partial.apply { parentFile!!.mkdirs(); writeBytes(apk.copyOf(50_000)) }
        val server = FakeServer(apk, ranges = false)
        assertArrayEquals(apk, download().run(server.opener(), always).readBytes())
        assertEquals(listOf(50_000L), server.offsets)
    }

    @Test fun aResumeAtTheWrongOffsetIsNotAppended() {
        download().partial.apply { parentFile!!.mkdirs(); writeBytes(apk.copyOf(50_000)) }
        val server = FakeServer(apk, answer = { ResumableDownload.Answer(206, "bytes 40000-${apk.size - 1}/${apk.size}", ByteArrayInputStream(apk, 40_000, apk.size - 40_000)) })
        assertTrue(runCatching { download().run(server.opener(), always) }.exceptionOrNull() is IOException)
        assertEquals(50_000L, download().partial.length())
        val wrongTotal = FakeServer(apk, answer = { ResumableDownload.Answer(206, "bytes 50000-${apk.size}/${apk.size + 1}", ByteArrayInputStream(apk, 50_000, apk.size - 50_000)) })
        assertTrue(runCatching { download().run(wrongTotal.opener(), always) }.exceptionOrNull() is IOException)
    }

    @Test fun unsatisfiableRangeStartsOverOnce() {
        download().partial.apply { parentFile!!.mkdirs(); writeBytes(apk.copyOf(10)) }
        var first = true
        val server = FakeServer(apk, answer = { offset ->
            if (first) { first = false; ResumableDownload.Answer(416, null, ByteArrayInputStream(ByteArray(0))) }
            else { assertEquals(0L, offset); ResumableDownload.Answer(200, null, ByteArrayInputStream(apk)) }
        })
        assertArrayEquals(apk, download().run(server.opener(), always).readBytes())
        val stuck = FakeServer(apk, answer = { ResumableDownload.Answer(416, null, ByteArrayInputStream(ByteArray(0))) })
        File(directory(), "${apkHash}.apk").delete()
        download().partial.writeBytes(apk.copyOf(10))
        assertTrue(runCatching { download().run(stuck.opener(), always) }.exceptionOrNull() is IOException)
    }

    @Test fun tamperedBytesAreRefusedAndDeleted() {
        val tampered = apk.copyOf().also { it[1234] = (it[1234] + 1).toByte() }
        val failure = runCatching { download().run(FakeServer(tampered).opener(), always) }.exceptionOrNull()
        assertEquals(UpdateRefused.Reason.HASH, (failure as UpdateRefused).reason)
        assertFalse(download().partial.exists()); assertFalse(download().finished.exists())
    }

    @Test fun wrongSizesAreRefusedAndDeleted() {
        val longer = apk + byteArrayOf(1, 2, 3)
        assertEquals(UpdateRefused.Reason.SIZE, (runCatching { download().run(FakeServer(longer).opener(), always) }.exceptionOrNull() as UpdateRefused).reason)
        assertFalse(download().partial.exists())
        val shorter = apk.copyOf(apk.size - 1)
        assertEquals(UpdateRefused.Reason.SIZE, (runCatching { download().run(FakeServer(shorter).opener(), always) }.exceptionOrNull() as UpdateRefused).reason)
        assertFalse(download().partial.exists())
    }

    @Test fun hubReleasesWithoutASizeAreStillHashChecked() {
        val unsized = release(3575000, bytes = null)
        assertArrayEquals(apk, download(unsized).run(FakeServer(apk).opener(), always).readBytes())
        File(directory(), "$apkHash.apk").delete()
        val other = Random(8).nextBytes(1000)
        assertEquals(UpdateRefused.Reason.HASH, (runCatching { download(unsized).run(FakeServer(other).opener(), always) }.exceptionOrNull() as UpdateRefused).reason)
    }

    @Test fun aVerifiedFinishedFileIsReusedWithoutTheNetwork() {
        download().run(FakeServer(apk).opener(), always)
        val offline = ResumableDownload.Opener { throw IOException("offline") }
        assertArrayEquals(apk, download().run(offline, always).readBytes())
        // A finished file that no longer matches is deleted and downloaded again.
        download().finished.writeBytes(apk.copyOf(10))
        assertTrue(runCatching { download().run(offline, always) }.exceptionOrNull() is IOException)
        assertFalse(download().finished.exists())
    }

    @Test fun otherReleasesFilesAreRemoved() {
        directory().mkdirs()
        val stale = File(directory(), "${"0".repeat(64)}.apk.part").apply { writeBytes(byteArrayOf(1)) }
        download().run(FakeServer(apk).opener(), always)
        assertFalse(stale.exists())
    }

    @Test fun httpErrorsAreFailuresNotFiles() {
        val server = FakeServer(apk, answer = { ResumableDownload.Answer(503, null, ByteArrayInputStream(ByteArray(0))) })
        assertTrue(runCatching { download().run(server.opener(), always) }.exceptionOrNull() is IOException)
        assertFalse(download().finished.exists())
    }

    // --- Build variants ---

    @Test fun onlyDebugBuildsCanRedirectTheUpdater() {
        val redirectable = UpdateDebugOverride::class.java.declaredMethods.any { it.name.startsWith("valid") }
        assertEquals(BuildConfig.BUILD_TYPE == "debug", redirectable)
    }
}
