package com.castle.sefirah

import android.app.Application
import androidx.hilt.work.HiltWorkerFactory
import androidx.work.Configuration
import dagger.hilt.android.HiltAndroidApp
import javax.inject.Inject

@HiltAndroidApp
class MainApplication : Application(), Configuration.Provider {

    override fun onCreate() {
        super.onCreate()
        com.orionmini.mobile.OrionBackupWorker.schedule(this)
        // Camera and phone screen requests pop up inside Saiph while it is open.
        com.orionmini.mobile.ForegroundActivity.register(this)
        // A daily check that only notifies; it honours Settings > Version and updates.
        com.orionmini.mobile.UpdateCheckWorker.schedule(this)
        // Counts only event types, and only after the owner agrees to anonymous usage statistics.
        sefirah.network.orion.OrionLink.published = { type -> com.orionmini.mobile.UsageAnalytics.event(this, type) }
        // Failures and crashes by fixed reason only, under the same agreement.
        sefirah.network.orion.OrionLink.failed = { com.orionmini.mobile.UsageAnalytics.failure(this, "hub_connection_failed") }
        sefirah.network.orion.HostedHttpTransport.failed = { code -> com.orionmini.mobile.UsageAnalytics.failure(this, code) }
        com.orionmini.mobile.UsageAnalytics.installCrashCounter(this)
    }

    @Inject lateinit var workerFactory: HiltWorkerFactory

    override val workManagerConfiguration: Configuration
        get() = Configuration.Builder()
            .setWorkerFactory(workerFactory)
            .build()
}
