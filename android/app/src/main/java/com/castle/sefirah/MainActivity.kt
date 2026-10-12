package com.castle.sefirah

import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.annotation.RequiresApi
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
import androidx.navigation.compose.rememberNavController
import com.castle.sefirah.navigation.OnboardingRoute
import com.castle.sefirah.navigation.graphs.RootNavGraph
import com.castle.sefirah.presentation.common.components.PairingRequestDialog
import com.castle.sefirah.presentation.sync.QrConnectionDialog
import com.castle.sefirah.presentation.sync.SyncViewModel
import com.castle.sefirah.ui.theme.SefirahTheme
import dagger.hilt.android.AndroidEntryPoint
import sefirah.common.notifications.AppNotifications
import sefirah.domain.interfaces.NetworkManager
import javax.inject.Inject
import sefirah.network.util.QrCodeParser

@AndroidEntryPoint
class MainActivity : ComponentActivity() {
    @Inject lateinit var networkManager: NetworkManager
    private val viewModel by viewModels<MainViewModel>()
    private val syncViewModel by viewModels<SyncViewModel>()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        installSplashScreen()
        networkManager.startService()

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            setupNotificationChannels()
        }
        enableEdgeToEdge()

        parsePairDeepLink(intent)?.let(syncViewModel::showQrConnection)
        clearDeepLinkIntent(intent)

        setContent {
            SefirahTheme {
                val pendingApproval by viewModel.pendingDeviceApproval.collectAsState()
                val pendingQrConnection by syncViewModel.pendingQrConnection.collectAsState()
                val navController = rememberNavController()
                val hasCompletedOnboarding = viewModel.startDestination != OnboardingRoute.OnboardingScreen.route

                Box(
                    modifier = Modifier
                        .background(color = MaterialTheme.colorScheme.background)
                        .fillMaxSize()
                ) {
                    RootNavGraph(
                        startDestination = viewModel.startDestination,
                        rootNavController = navController,
                    )

                    if (hasCompletedOnboarding) {
                        pendingQrConnection?.let { connectionData ->
                            QrConnectionDialog(
                                connectionData = connectionData,
                                onDismiss = syncViewModel::dismissQrConnection,
                                onConnect = { connectionDetails ->
                                    syncViewModel.connectFromQrCode(connectionDetails, navController)
                                },
                            )
                        }
                    }

                    pendingApproval?.let { approval ->
                        PairingRequestDialog(
                            deviceName = approval.deviceName,
                            verificationCode = approval.verificationCode,
                            onDismiss = { viewModel.rejectDevice(approval.deviceId) },
                            onApprove = { viewModel.approveDevice(approval.deviceId) },
                            onReject = { viewModel.rejectDevice(approval.deviceId) },
                        )
                    }
                }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        parsePairDeepLink(intent)?.let(syncViewModel::showQrConnection)
        clearDeepLinkIntent(intent)
    }

    private fun parsePairDeepLink(intent: Intent?) =
        intent?.takeIf { it.action == Intent.ACTION_VIEW }?.data?.let(QrCodeParser::parsePairDeepLink)

    private fun clearDeepLinkIntent(intent: Intent?) {
        if (intent?.action != Intent.ACTION_VIEW) return
        setIntent(Intent(intent).apply { data = null })
    }

    @RequiresApi(Build.VERSION_CODES.O)
    private fun setupNotificationChannels() {
        try {
            AppNotifications.createChannels(this)
        } catch (e: Exception) {
            Log.e("MainActivity", "Error creating notification channels", e)
        }
    }
}