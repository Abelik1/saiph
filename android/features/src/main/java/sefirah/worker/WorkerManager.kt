package sefirah.worker

import android.content.Context
import android.os.IBinder
import sefirah.domain.interfaces.NetworkManager
import javax.inject.Inject
import javax.inject.Singleton
import kotlin.concurrent.thread

/** The bundled worker is started through an already authorized desktop ADB connection. */
@Singleton
class WorkerManager @Inject constructor(
    private val context: Context,
    private val networkManager: NetworkManager,
) {
    @Volatile private var worker: IWorkerService? = null
    @Volatile private var watching = false
    fun isWatching(): Boolean = watching
    fun startClipboardWatcher() {
        watching = true
        thread(name = "orion-worker-start", isDaemon = true) {
            try {
                val current = worker
                if (current != null && current.asBinder().pingBinder() && current.version == WORKER_VERSION) {
                    current.startWatching()
                    context.getSharedPreferences("orion",0).edit().putBoolean("worker_ready",true).apply()
                    networkManager.refreshCapabilities()
                } else {
                    worker = null
                    // No phone-supplied executable string crosses the bus.
                    networkManager.refreshCapabilities()
                }
            } catch (_: Exception) { worker = null; networkManager.refreshCapabilities() }
        }
    }
    fun stopClipboardWatcher() {
        watching = false
        context.getSharedPreferences("orion",0).edit().putBoolean("worker_ready",false).apply()
        networkManager.refreshCapabilities()
        try { worker?.stopWatching() } catch (_: Exception) { worker = null }
    }
    fun suppressNextOutbound() { try { worker?.suppressNextOutbound() } catch (_: Exception) { worker = null } }
    fun isWorkerAlive(): Boolean = try { worker?.asBinder()?.pingBinder() == true } catch (_: Exception) { false }
    fun registerWorker(binder: IBinder) {
        val candidate = IWorkerService.Stub.asInterface(binder)
        if (runCatching { candidate.version }.getOrNull() != WORKER_VERSION) {
            runCatching { candidate.destroy() }; return
        }
        runCatching { worker?.takeIf { it.asBinder() != binder }?.destroy() }
        binder.linkToDeath({
            if (worker?.asBinder() == binder) {
                worker = null
                context.getSharedPreferences("orion",0).edit().putBoolean("worker_ready",false).apply()
                networkManager.refreshCapabilities()
            }
        }, 0)
        worker = candidate
        context.getSharedPreferences("orion",0).edit().putBoolean("worker_ready",watching).apply()
        if (watching) runCatching { candidate.startWatching() }
        networkManager.refreshCapabilities()
    }
    companion object {
        const val NICE_NAME = "sefirah_worker"
        const val WORKER_VERSION = 2
    }
}
