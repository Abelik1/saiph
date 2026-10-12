package com.orionmini.mobile
import android.os.Binder
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import android.net.Uri
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import sefirah.worker.WorkerBridgeProvider

@RunWith(AndroidJUnit4::class)
class WorkerBridgeTest {
    @Test fun appUidsCannotImpersonateTheShellWorker() {
        WorkerBridgeProvider.requireShell(0)
        WorkerBridgeProvider.requireShell(2000)
        for(uid in listOf(1000,10001,20001)) {
            try { WorkerBridgeProvider.requireShell(uid);fail("App UID accepted") } catch(_:SecurityException) {}
        }
        val context=InstrumentationRegistry.getInstrumentation().targetContext
        try {
            context.contentResolver.call(Uri.parse("content://com.orionmini.mobile.worker.bridge"),"status",null,null)
            fail("Ordinary app caller accepted")
        } catch(_:SecurityException) {}
    }
}
