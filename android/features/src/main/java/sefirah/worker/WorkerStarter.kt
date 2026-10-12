package sefirah.worker

import android.content.Context
import java.io.File

/** Paths and commands for `libsefirah_worker.so` */
object WorkerStarter {
    const val LIB_NAME = "libsefirah_worker.so"

    fun starterFile(context: Context): File =
        File(context.applicationInfo.nativeLibraryDir, LIB_NAME)

    /** Run from root/adb shell: execs app_process with the host APK as classpath. */
    fun command(context: Context): String =
        "${starterFile(context).absolutePath} --apk=${context.applicationInfo.sourceDir}"
}