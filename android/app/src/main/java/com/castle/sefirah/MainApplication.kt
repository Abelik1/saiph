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
        // Counts only event types, and only after the owner agrees to anonymous usage statistics.
        sefirah.network.orion.OrionLink.published = { type -> com.orionmini.mobile.UsageAnalytics.event(this, type) }
    }

    @Inject lateinit var workerFactory: HiltWorkerFactory

    override val workManagerConfiguration: Configuration
        get() = Configuration.Builder()
            .setWorkerFactory(workerFactory)
            .build()
}
