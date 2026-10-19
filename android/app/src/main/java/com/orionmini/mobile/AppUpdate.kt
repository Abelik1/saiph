// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.longOrNull
import java.io.File
import java.io.IOException
import java.io.InputStream
import java.io.RandomAccessFile
import java.security.MessageDigest

/**
 * The in-app updater's rules, kept free of Android so every refusal can be tested on the JVM.
 *
 * An update is accepted only when all of these hold, in this order:
 * 1. the official source's description of the build parses strictly ([UpdateManifest]);
 * 2. it is newer than this install and runs on this phone ([UpdatePolicy]);
 * 3. the downloaded bytes have exactly the published size and SHA-256 ([ResumableDownload]);
 * 4. the APK names this app, the published version, and the very certificates the installed
 *    app is signed with ([UpdateVerifier]).
 * Then Android's own installer asks the person to confirm. Nothing installs silently.
 */
data class AppRelease(
    val versionCode: Long,
    val versionName: String,
    val sha256: String,
    /** Exact APK size. Older self-hosted Hubs do not publish it; then [MAX_APK_BYTES] bounds the download. */
    val bytes: Long?,
    /** What's new, shown before downloading. Empty when the source has none. */
    val notes: String,
    val minSdk: Int?,
) {
    val label get() = "$versionName (build $versionCode)"

    companion object {
        const val MAX_APK_BYTES = 200_000_000L
        /** Android's ceiling for versionCode. */
        const val MAX_VERSION_CODE = 2_100_000_000L
    }
}

/** Why an update was not offered or not installed. The message is what the person reads. */
class UpdateRefused(val reason: Reason) : Exception(reason.message) {
    enum class Reason(val message: String) {
        MANIFEST("The update information from Saiph wasn't valid, so nothing was downloaded."),
        DOWNGRADE("The published build is older than the one on this phone. Saiph never installs an older version."),
        INCOMPATIBLE("This update needs a newer version of Android than this phone has."),
        SIZE("The download wasn't the published size. It was deleted; try again."),
        HASH("The download doesn't match the published build. It was deleted; try again."),
        UNREADABLE("Android couldn't read the downloaded app. It was deleted; try again."),
        PACKAGE("The download isn't Saiph for this phone. It was deleted."),
        VERSION("The download isn't the version that was published. It was deleted."),
        SIGNER("The download isn't signed by Saiph's publisher, so it was deleted. Your installed app is unchanged."),
    }
}

/** Strict readers for each official source's release description. Anything unexpected is refused. */
object UpdateManifest {
    const val PACKAGE = "com.orionmini.mobile"
    private const val MAX_BYTES = 16 * 1024
    private const val MAX_NOTES = 4000
    private val HASH = Regex("[a-f0-9]{64}")
    private val VERSION = Regex("[0-9]{1,4}\\.[0-9]{1,4}\\.[0-9]{1,6}(?:-[A-Za-z0-9.]{1,32})?")
    /** Hub administrators choose their own names; still one short printable token. */
    private val HUB_VERSION = Regex("[0-9A-Za-z][0-9A-Za-z._+-]{0,63}")
    private val HOSTED_KEYS = setOf("schema", "package", "version_code", "version_name", "sha256", "bytes", "min_sdk", "notes")
    private val HUB_KEYS = setOf("version_code", "version_name", "sha256", "size", "published_at")

    /**
     * The Saiph account's description of the current Android build (schema 1, proposed in
     * docs/ANDROID_UPDATES.md). Every key is required and no other key is allowed.
     */
    fun hosted(raw: ByteArray): AppRelease = refuseUnless {
        val value = parse(raw) as JsonObject
        check(value.keys == HOSTED_KEYS)
        check(integer(value, "schema") == 1L && string(value, "package") == PACKAGE)
        val name = string(value, "version_name")
        check(VERSION.matches(name))
        val bytes = integer(value, "bytes")
        check(bytes in 1..AppRelease.MAX_APK_BYTES)
        val minSdk = integer(value, "min_sdk")
        check(minSdk in 21L..99L)
        AppRelease(versionCode(value), name, hash(value, "sha256"), bytes, notes(string(value, "notes")), minSdk.toInt())
    }

    /** A self-hosted Hub's `/v1/app/android` answer: `{"release": {...}}`, or a null release when none is published. */
    fun hub(raw: ByteArray): AppRelease? = refuseUnless {
        val value = parse(raw) as JsonObject
        check(value.keys == setOf("release"))
        val release = value.getValue("release")
        if (release is JsonNull) return@refuseUnless null
        release as JsonObject
        check(release.keys.containsAll(listOf("version_code", "version_name", "sha256")) && HUB_KEYS.containsAll(release.keys))
        val name = string(release, "version_name")
        check(HUB_VERSION.matches(name))
        val size = if ("size" in release) integer(release, "size").also { check(it in 1..AppRelease.MAX_APK_BYTES) } else null
        if ("published_at" in release) check(string(release, "published_at").length <= 64)
        AppRelease(versionCode(release), name, hash(release, "sha256"), size, "", null)
    }

    private inline fun <T> refuseUnless(read: () -> T): T = try { read() }
        catch (refused: UpdateRefused) { throw refused }
        catch (_: Exception) { throw UpdateRefused(UpdateRefused.Reason.MANIFEST) }

    /** Bounded, ASCII-or-UTF-8 JSON without repeated keys: a repeated key could show one value and install another. */
    internal fun parse(raw: ByteArray): JsonElement {
        check(raw.size in 2..MAX_BYTES)
        val text = Charsets.UTF_8.newDecoder().decode(java.nio.ByteBuffer.wrap(raw)).toString()
        val element = Json.parseToJsonElement(text)
        check(keyCount(element) == declaredKeys(text))
        return element
    }

    private fun keyCount(element: JsonElement): Int = when (element) {
        is JsonObject -> element.size + element.values.sumOf(::keyCount)
        is JsonArray -> element.sumOf(::keyCount)
        else -> 0
    }

    /** Strings followed by a colon are keys; the parser keeps only the last of a repeated one. */
    private fun declaredKeys(text: String): Int {
        var count = 0; var index = 0
        while (index < text.length) {
            if (text[index] != '"') { index++; continue }
            index++
            while (text[index] != '"') index += if (text[index] == '\\') 2 else 1
            index++
            var next = index
            while (next < text.length && text[next] in " \t\r\n") next++
            if (next < text.length && text[next] == ':') count++
        }
        return count
    }

    private fun primitive(value: JsonObject, key: String) = value.getValue(key) as JsonPrimitive
    private fun string(value: JsonObject, key: String): String = primitive(value, key).also { check(it.isString) }.content
    private fun integer(value: JsonObject, key: String): Long = primitive(value, key).also { check(!it.isString) }.longOrNull!!
    private fun versionCode(value: JsonObject) = integer(value, "version_code").also { check(it in 1..AppRelease.MAX_VERSION_CODE) }
    private fun hash(value: JsonObject, key: String) = string(value, key).also { check(HASH.matches(it)) }
    private fun notes(value: String): String {
        check(value.length <= MAX_NOTES && value.none { it.code < 32 && it != '\n' || it.code == 127 || it in '‪'..'‮' || it in '⁦'..'⁩' })
        return value.trim()
    }
}

/** Whether a published build is worth offering to this phone. Only the versionCode decides; names are for people. */
object UpdatePolicy {
    enum class Decision { NEWER, CURRENT, DOWNGRADE, INCOMPATIBLE }

    fun decide(installedCode: Long, release: AppRelease, sdk: Int): Decision = when {
        release.versionCode < installedCode -> Decision.DOWNGRADE
        release.versionCode == installedCode -> Decision.CURRENT
        release.minSdk != null && release.minSdk > sdk -> Decision.INCOMPATIBLE
        else -> Decision.NEWER
    }

    /** "55 MB": what a metered-network question and the download button show. */
    fun size(bytes: Long?): String = when {
        bytes == null -> "size unknown"
        bytes >= 1_000_000 -> "${(bytes + 500_000) / 1_000_000} MB"
        else -> "${maxOf(1, (bytes + 500) / 1000)} kB"
    }
}

/** What Android reports about an APK or the installed app: its package, version and current signers. */
data class PackageFacts(val packageName: String, val versionCode: Long, val signers: Set<String>)

object UpdateVerifier {
    fun sha256(file: File): String = file.inputStream().use(::sha256)

    fun sha256(input: InputStream): String {
        val digest = MessageDigest.getInstance("SHA-256"); val buffer = ByteArray(1 shl 16)
        while (true) { val count = input.read(buffer); if (count < 0) break; digest.update(buffer, 0, count) }
        return hex(digest.digest())
    }

    /** A certificate's identity as Saiph's publishing docs print it: lowercase SHA-256 of the DER bytes. */
    fun certificate(der: ByteArray): String = hex(MessageDigest.getInstance("SHA-256").digest(der))

    /**
     * The downloaded APK must be this app, exactly the published version, newer than what is
     * installed, and signed by exactly the installed app's certificates. Android also refuses a
     * different signer, but only after the person has been asked; this refuses first. A future
     * signing-key rotation would be refused here too and needs an updater change.
     */
    fun check(archive: PackageFacts?, installed: PackageFacts, release: AppRelease) {
        archive ?: throw UpdateRefused(UpdateRefused.Reason.UNREADABLE)
        if (archive.packageName != installed.packageName) throw UpdateRefused(UpdateRefused.Reason.PACKAGE)
        if (archive.versionCode != release.versionCode) throw UpdateRefused(UpdateRefused.Reason.VERSION)
        if (archive.versionCode <= installed.versionCode) throw UpdateRefused(UpdateRefused.Reason.DOWNGRADE)
        if (installed.signers.isEmpty() || archive.signers != installed.signers) throw UpdateRefused(UpdateRefused.Reason.SIGNER)
    }

    private fun hex(bytes: ByteArray) = bytes.joinToString("") { "%02x".format(it) }
}

/**
 * Downloads one release into app-private storage, resuming a partial file with an HTTP Range
 * request. Files are named by the published SHA-256, so a different release never appends to
 * an old partial. The finished file exists only after its size and hash were checked; anything
 * that fails a check is deleted.
 */
class ResumableDownload(private val directory: File, private val release: AppRelease) {
    /** One HTTP answer: status, Content-Range (for 206) and the body. The caller closes nothing; [body] is closed here. */
    class Answer(val code: Int, val contentRange: String?, val body: InputStream)

    fun interface Opener { fun open(offset: Long): Answer }

    val partial = File(directory, "${release.sha256}.apk.part")
    val finished = File(directory, "${release.sha256}.apk")
    private val limit = release.bytes ?: AppRelease.MAX_APK_BYTES

    /** Delete other releases' files, keeping this release's partial so it can resume. */
    fun clearOthers() {
        directory.listFiles()?.filter { it != partial && it != finished }?.forEach { it.delete() }
    }

    /**
     * Returns the verified file. [progress] gets (bytes so far, total or null) and returns false
     * to stop; a stopped download keeps its partial file and throws [IOException].
     */
    fun run(opener: Opener, progress: (Long, Long?) -> Boolean): File {
        check(directory.isDirectory || directory.mkdirs())
        clearOthers()
        if (finished.exists()) {
            if (verified(finished)) return finished
            finished.delete()
        }
        var restarted = false
        while (true) {
            if (partial.length() > limit || (release.bytes != null && partial.length() == release.bytes && !verified(partial))) partial.delete()
            val offset = partial.length()
            if (release.bytes == null || offset < release.bytes) {
                val answer = opener.open(offset)
                try {
                    when {
                        answer.code == 416 && !restarted -> { partial.delete(); restarted = true; continue }
                        answer.code == 206 && offset > 0 -> { check206(answer.contentRange, offset); write(answer.body, offset, progress) }
                        answer.code == 200 -> write(answer.body, 0, progress)
                        else -> throw IOException("Download failed (HTTP ${answer.code})")
                    }
                } finally { answer.body.close() }
            }
            if (release.bytes != null && partial.length() != release.bytes) {
                partial.delete(); throw UpdateRefused(UpdateRefused.Reason.SIZE)
            }
            if (!verified(partial)) { partial.delete(); throw UpdateRefused(UpdateRefused.Reason.HASH) }
            check(partial.renameTo(finished))
            return finished
        }
    }

    private fun verified(file: File) = (release.bytes == null || file.length() == release.bytes) &&
        UpdateVerifier.sha256(file) == release.sha256

    /** `bytes START-END/TOTAL`: the server must continue exactly where the partial file ends. */
    private fun check206(header: String?, offset: Long) {
        val match = Regex("bytes ([0-9]{1,12})-([0-9]{1,12})/([0-9]{1,12}|\\*)").matchEntire(header?.trim().orEmpty())
            ?: throw IOException("Download could not resume")
        val (start, end, total) = match.destructured
        if (start.toLong() != offset || end.toLong() < offset || (release.bytes != null && total != release.bytes.toString()))
            throw IOException("Download could not resume")
    }

    private fun write(body: InputStream, offset: Long, progress: (Long, Long?) -> Boolean) {
        RandomAccessFile(partial, "rw").use { file ->
            file.setLength(offset); file.seek(offset)
            var written = offset; val buffer = ByteArray(1 shl 16)
            if (!progress(written, release.bytes)) throw IOException("Download paused")
            while (true) {
                val count = body.read(buffer)
                if (count < 0) break
                if (written + count > limit) { file.close(); partial.delete(); throw UpdateRefused(UpdateRefused.Reason.SIZE) }
                file.write(buffer, 0, count); written += count
                if (!progress(written, release.bytes)) { file.fd.sync(); throw IOException("Download paused") }
            }
            file.fd.sync()
        }
    }
}
