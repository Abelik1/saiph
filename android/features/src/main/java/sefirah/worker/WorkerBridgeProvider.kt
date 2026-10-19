package sefirah.worker

import android.content.ContentProvider
import android.content.ContentValues
import android.database.Cursor
import android.net.Uri
import android.os.Bundle
import android.os.Binder
import android.os.ParcelFileDescriptor
import android.util.Log
import dagger.hilt.EntryPoint
import dagger.hilt.InstallIn
import dagger.hilt.android.EntryPointAccessors
import dagger.hilt.components.SingletonComponent
import sefirah.clipboard.ClipboardFeature
import sefirah.domain.interfaces.NetworkManager

/**
 * app_process cannot bindService, so the worker hands its [IWorkerService] binder over via [call].
 */
class WorkerBridgeProvider : ContentProvider() {

    private lateinit var workerManager: WorkerManager
    private lateinit var clipboardFeature: ClipboardFeature
    private lateinit var networkManager: NetworkManager

    private val hostBridge = object : IHostBridge.Stub() {
        override fun onClipboardText(text: String?) {
            requireShell()
            if (text.isNullOrEmpty()) return
            clipboardFeature.onWorkerClipboardText(text)
        }

        override fun onClipboardImage(mimeType: String?, fd: ParcelFileDescriptor?) {
            try { requireShell() } catch (error: SecurityException) { fd?.close(); throw error }
            if (mimeType.isNullOrEmpty() || fd == null) {
                try {
                    fd?.close()
                } catch (_: Exception) {
                }
                return
            }
            clipboardFeature.onWorkerClipboardImage(mimeType, fd)
        }
    }

    override fun onCreate(): Boolean {
        val entry = EntryPointAccessors.fromApplication(
            context!!.applicationContext,
            BridgeEntryPoint::class.java,
        )
        workerManager = entry.workerManager()
        clipboardFeature = entry.clipboardFeature()
        networkManager = entry.networkManager()
        return true
    }

    override fun call(method: String, arg: String?, extras: Bundle?): Bundle? {
        requireShell()
        if (method == "status") return Bundle().apply {
            val app = context!!
            putString("device_id", networkManager.clipboardDeviceId().orEmpty())
            putString("mode", networkManager.clipboardConnectionMode)
            putBoolean("worker_alive", workerManager.isWorkerAlive())
            putBoolean("watching", workerManager.isWatching())
            putString("starter", WorkerStarter.starterFile(app).absolutePath)
            putString("apk", app.applicationInfo.sourceDir)
        }
        if (method != METHOD_SEND_BINDER) {
            return null
        }
        val workerBinder = extras?.getBinder(EXTRA_BINDER)
        if (workerBinder == null) {
            Log.w(TAG, "sendBinder missing binder")
            return null
        }
        workerManager.registerWorker(workerBinder)
        return Bundle().apply {
            putBinder(EXTRA_BINDER, hostBridge.asBinder())
        }
    }

    override fun query(
        uri: Uri,
        projection: Array<out String>?,
        selection: String?,
        selectionArgs: Array<out String>?,
        sortOrder: String?,
    ): Cursor? = null

    override fun getType(uri: Uri): String? = null

    override fun insert(uri: Uri, values: ContentValues?): Uri? = null

    override fun delete(uri: Uri, selection: String?, selectionArgs: Array<out String>?): Int = 0

    override fun update(
        uri: Uri,
        values: ContentValues?,
        selection: String?,
        selectionArgs: Array<out String>?,
    ): Int = 0

    @EntryPoint
    @InstallIn(SingletonComponent::class)
    interface BridgeEntryPoint {
        fun workerManager(): WorkerManager
        fun clipboardFeature(): ClipboardFeature
        fun networkManager(): NetworkManager
    }

    companion object {
        fun requireShell(uid: Int = Binder.getCallingUid()) {
            if (uid != 2000 && uid != 0) throw SecurityException("Authorized debugging required")
        }
        private const val TAG = "WorkerBridge"
        private const val METHOD_SEND_BINDER = "sendBinder"
        private const val EXTRA_BINDER = "sefirah.intent.extra.BINDER"
    }
}
