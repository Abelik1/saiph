package sefirah.clipboard

import android.annotation.SuppressLint
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.net.Uri
import android.os.Build
import android.os.ParcelFileDescriptor
import android.util.Base64
import android.util.Log
import dagger.Lazy
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import sefirah.Feature
import sefirah.common.util.createTempFile
import sefirah.common.util.getFileProviderUri
import sefirah.domain.interfaces.DeviceManager
import sefirah.domain.interfaces.NetworkManager
import sefirah.domain.interfaces.PreferencesRepository
import sefirah.domain.model.ClipboardInfo
import sefirah.domain.model.DevicePreferences
import sefirah.domain.model.FileMetadata
import sefirah.transfer.FileTransferService
import sefirah.worker.WorkerManager
import java.io.FileInputStream
import java.io.FileOutputStream
import java.io.IOException
import javax.inject.Inject
import javax.inject.Singleton

/** What sending the current clipboard did, for the clipboard bubble's answer. */
enum class ClipboardSend { SENT, EMPTY, NOT_SENT }

@Singleton
class ClipboardFeature @Inject constructor(
    deviceManager: DeviceManager,
    private val context: Context,
    private val networkManager: NetworkManager,
    private val preferencesRepository: PreferencesRepository,
    private val fileTransferService: Lazy<FileTransferService>,
    private val workerManager: WorkerManager,
) : Feature(deviceManager) {
    private val clipboardManager = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)

    private val clipChangedListener = ClipboardManager.OnPrimaryClipChangedListener {
        scope.launch { sendPrimaryClipboard() }
    }

    init {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            scope.launch {
                preferencesRepository.readClipboardWorkerEnabled().collect {
                    applyWorkerState(it)
                }
            }
        }
    }

    /**
     * App-side suppress for the non-worker clip listener (sync callbacks during setPrimaryClip).
     * Worker echo is handled in the shell worker via [WorkerManager.suppressNextOutbound].
     */
    @Volatile
    var suppressOutbound: Boolean = false
        private set

    override fun isPrefEnabled(prefs: DevicePreferences) = prefs.clipboardSync

    override suspend fun onStart(deviceId: String) {
        if (enabledDevices.size != 1) return
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) {
            clipboardManager.addPrimaryClipChangedListener(clipChangedListener)
        } else {
            applyWorkerState(preferencesRepository.readClipboardWorkerEnabled().first())
        }
    }

    override suspend fun onStop(deviceId: String) {
        if (enabledDevices.isNotEmpty()) return
        clipboardManager.removePrimaryClipChangedListener(clipChangedListener)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            workerManager.stopClipboardWatcher()
        }
    }

    /** Worker runs only when sync is active for a device and the worker pref is on. */
    private fun applyWorkerState(workerSync: Boolean) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) return
        scope.launch {
            if (enabledDevices.isNotEmpty() && workerSync) {
                workerManager.startClipboardWatcher()
            } else {
                workerManager.stopClipboardWatcher()
            }
        }
    }

    fun onWorkerClipboardText(text: String) {
        sendClipboard(ClipboardInfo("text/plain", text))
    }

    fun onWorkerClipboardImage(mimeType: String, fd: ParcelFileDescriptor) {
        scope.launch { sendClipboardImage(mimeType, fd) }
    }

    fun setClipboard(clipboard: ClipboardInfo) {
        if (!context.getSharedPreferences("orion",0).getBoolean("clipboard_enabled",true)) return
        try {
            val clip: ClipData = when {
                clipboard.clipboardType == "text/plain" ->
                    ClipData.newPlainText("Received clipboard", clipboard.content)

                clipboard.clipboardType.startsWith("image/") -> {
                    val imageBytes = Base64.decode(clipboard.content, Base64.DEFAULT)
                    val extension = clipboard.clipboardType.substringAfter('/').lowercase()

                    val tempFile = createTempFile(context, FileMetadata.CLIPBOARD_FILE_NAME, extension)
                    FileOutputStream(tempFile).use { it.write(imageBytes) }

                    val uri = getFileProviderUri(context, tempFile)
                    ClipData.newUri(context.contentResolver, "Received image", uri)
                }

                else -> ClipData.newPlainText("Received clipboard", clipboard.content)
            }
            suppressOutbound()
            clipboardManager.setPrimaryClip(clip)
        } catch (ex: Exception) {
            Log.e(TAG, "Exception handling clipboard")
        } finally {
            suppressOutbound = false
        }
    }

    fun setClipboardUri(uri: Uri) {
        if (!context.getSharedPreferences("orion",0).getBoolean("clipboard_enabled",true)) return
        try {
            suppressOutbound()
            val clip = ClipData.newUri(context.contentResolver, "Received file", uri)
            clipboardManager.setPrimaryClip(clip)
        } catch (ex: Exception) {
            Log.e(TAG, "Exception setting clipboard URI")
        } finally {
            suppressOutbound = false
        }
    }

    private fun suppressOutbound() {
        if (workerManager.isWorkerAlive()) {
            workerManager.suppressNextOutbound()
        } else {
            suppressOutbound = true
        }
    }

    /** True when at least one connected computer took it. */
    fun sendClipboard(message: ClipboardInfo): Boolean {
        if (enabledDevices.isEmpty()) {
            return false
        }
        val targets = enabledDevices.toList()
        Log.d(TAG, "broadcasting clipboard | ${message.clipboardType}")
        return targets.map { deviceId -> networkManager.sendMessage(deviceId, message) }.any { it }
    }


    /** Sends what is on the clipboard now. Android allows the read only while a Saiph window has focus. */
    @SuppressLint("Recycle")
    suspend fun sendPrimaryClipboard(): ClipboardSend {
        if (suppressOutbound) return ClipboardSend.NOT_SENT

        val clip = clipboardManager.primaryClip
        if (clip == null || clip.itemCount == 0) {
            return ClipboardSend.EMPTY
        }

        val item = clip.getItemAt(0)

        val text = item.text?.toString()
        if (!text.isNullOrEmpty()) {
            return if (sendClipboard(ClipboardInfo("text/plain", text))) ClipboardSend.SENT else ClipboardSend.NOT_SENT
        }

        val uri = item.uri
        if (uri != null && clip.description.hasMimeType("image/*")) {
            val mime = clip.description.filterMimeTypes("image/*")?.firstOrNull()
                ?: context.contentResolver.getType(uri)
                ?: "image/png"
            val pfd = try {
                withContext(Dispatchers.IO) {
                    context.contentResolver.openFileDescriptor(uri, "r")
                }
            } catch (e: Exception) {
                Log.e(TAG, "Clipboard image unavailable")
                return ClipboardSend.NOT_SENT
            }
            if (pfd == null) {
                Log.e(TAG, "Clipboard image unavailable")
                return ClipboardSend.NOT_SENT
            }
            return if (sendClipboardImage(mime, pfd)) ClipboardSend.SENT else ClipboardSend.NOT_SENT
        }
        return ClipboardSend.EMPTY
    }

    /**
     * Image FD from the shell worker or [sendPrimaryClipboard].
     * Known size ≤2MB → base64 [ClipboardInfo]. Larger → [FileTransferService.sendClipboard].
     */
    private suspend fun sendClipboardImage(mimeType: String, pfd: ParcelFileDescriptor): Boolean {
        val mime = mimeType.takeIf { it in setOf("image/png", "image/jpeg", "image/webp") }
        if (mime == null || enabledDevices.isEmpty()) { pfd.close(); return false }
        val file = java.io.File(context.cacheDir, "orion-clipboard-" + java.util.UUID.randomUUID() + "." + mime.substringAfter('/'))
        try {
            withContext(Dispatchers.IO) {
                ParcelFileDescriptor.AutoCloseInputStream(pfd).use { input -> file.outputStream().use { output ->
                    val buffer = ByteArray(65536); var total = 0L
                    while (true) {
                        val count = input.read(buffer); if (count < 0) break
                        total += count
                        if (total > networkManager.clipboardFileLimit) throw IOException("Clipboard file exceeds transfer limit")
                        output.write(buffer, 0, count)
                    }
                } }
            }
            // Orion publishes a direct clipboard offer up to 25 MB, otherwise a file offer.
            // No legacy LAN certificates or per-device Sefirah pairing are involved.
            if (networkManager.sendClipboardFile(mime, file)) return true
            file.delete()
        } catch (_: Exception) { file.delete(); Log.w(TAG, "Clipboard image transfer unavailable") }
        return false
    }

    /**
     * If [pfd] is a pipe (`statSize == -1`), copy into a cache file, then unlink the path
     * (fd stays valid until [ParcelFileDescriptor.close]). Takes ownership of [pfd].
     */
    @SuppressLint("Recycle")
    private fun asRegularFilePfd(pfd: ParcelFileDescriptor): ParcelFileDescriptor {
        if (pfd.statSize >= 0) {
            return pfd
        }
        val tmp = createTempFile(context, FileMetadata.CLIPBOARD_FILE_NAME, "img")
        try {
            ParcelFileDescriptor.AutoCloseInputStream(pfd).use { input ->
                FileOutputStream(tmp).use { output ->
                    val buf = ByteArray(DEFAULT_BUFFER_SIZE)
                    var total = 0L
                    while (true) {
                        val n = input.read(buf)
                        if (n <= 0) break
                        total += n
                        if (total > MAX_CLIPBOARD_IMAGE_BYTES) {
                            throw IOException("Clipboard image exceeds $MAX_CLIPBOARD_IMAGE_BYTES bytes")
                        }
                        output.write(buf, 0, n)
                    }
                }
            }
            val filePfd = ParcelFileDescriptor.open(tmp, ParcelFileDescriptor.MODE_READ_ONLY)
            tmp.delete()
            return filePfd
        } catch (e: Exception) {
            tmp.delete()
            throw e
        }
    }

    companion object {
        private const val TAG = "ClipboardFeature"
        private const val DIRECT_TRANSFER_THRESHOLD = 2 * 1024 * 1024 // 2MB
        private const val MAX_CLIPBOARD_IMAGE_BYTES = 32L * 1024 * 1024
    }
}
