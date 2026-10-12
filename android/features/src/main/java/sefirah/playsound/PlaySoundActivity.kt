package sefirah.playsound

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Build
import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import dagger.hilt.android.AndroidEntryPoint
import sefirah.common.R
import javax.inject.Inject

@AndroidEntryPoint
class PlaySoundActivity : ComponentActivity() {

    @Inject lateinit var playSoundFeature: PlaySoundFeature

    private val finishReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            if (intent.action == ACTION_FINISH) finish()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val deviceId = intent.getStringExtra(EXTRA_DEVICE_ID)
        if (deviceId.isNullOrBlank()) {
            finish()
            return
        }

        enableEdgeToEdge()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) {
            setShowWhenLocked(true)
            setTurnScreenOn(true)
        }

        @Suppress("DEPRECATION")
        window.addFlags(
            WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON or
                WindowManager.LayoutParams.FLAG_ALLOW_LOCK_WHILE_SCREEN_ON or
                WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED or
                WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON or
                WindowManager.LayoutParams.FLAG_DISMISS_KEYGUARD,
        )

        WindowCompat.setDecorFitsSystemWindows(window, false)
        WindowInsetsControllerCompat(window, window.decorView).apply {
            hide(WindowInsetsCompat.Type.navigationBars())
            systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        }

        ContextCompat.registerReceiver(
            this,
            finishReceiver,
            IntentFilter(ACTION_FINISH),
            ContextCompat.RECEIVER_NOT_EXPORTED,
        )

        val deviceName = intent.getStringExtra(EXTRA_DEVICE_NAME).orEmpty().ifBlank { deviceId }

        setContent {
            MaterialTheme(colorScheme = PlaySoundDarkColors) {
                PlaySoundScreen(
                    deviceName = deviceName,
                    onStop = {
                        playSoundFeature.stop(notifyRemote = true)
                        finish()
                    },
                )
            }
        }
    }

    override fun onDestroy() {
        runCatching { unregisterReceiver(finishReceiver) }
        super.onDestroy()
    }

    companion object {
        const val ACTION_FINISH = "sefirah.playsound.PlaySoundActivity.FINISH"
        private const val EXTRA_DEVICE_ID = "extra_device_id"
        private const val EXTRA_DEVICE_NAME = "extra_device_name"

        fun createIntent(context: Context, deviceId: String, deviceName: String): Intent =
            Intent(context, PlaySoundActivity::class.java).apply {
                putExtra(EXTRA_DEVICE_ID, deviceId)
                putExtra(EXTRA_DEVICE_NAME, deviceName)
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
            }
    }
}

private val PlaySoundDarkColors = darkColorScheme(
    primary = Color(0xFF8AB4F8),
    onPrimary = Color(0xFF062E6F),
    surface = Color(0xFF0B0B0F),
    onSurface = Color(0xFFF2F2F7),
    onSurfaceVariant = Color(0xFFB0B0B8),
)

@Composable
private fun PlaySoundScreen(
    deviceName: String,
    onStop: () -> Unit,
) {
    val pulse = rememberInfiniteTransition(label = "pulse")
    val scale by pulse.animateFloat(
        initialValue = 1f,
        targetValue = 1.12f,
        animationSpec = infiniteRepeatable(
            animation = tween(900, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "scale",
    )
    val ringAlpha by pulse.animateFloat(
        initialValue = 0.18f,
        targetValue = 0.42f,
        animationSpec = infiniteRepeatable(
            animation = tween(900, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "ringAlpha",
    )

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.surface)
            .systemBarsPadding()
            .padding(horizontal = 28.dp, vertical = 40.dp),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .align(Alignment.Center),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
        ) {
            Box(contentAlignment = Alignment.Center) {
                Box(
                    modifier = Modifier
                        .size(148.dp)
                        .scale(scale)
                        .background(
                            color = MaterialTheme.colorScheme.primary.copy(alpha = ringAlpha),
                            shape = CircleShape,
                        ),
                )
                Box(
                    modifier = Modifier
                        .size(104.dp)
                        .background(
                            color = MaterialTheme.colorScheme.primary.copy(alpha = 0.16f),
                            shape = CircleShape,
                        ),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(
                        painter = painterResource(R.drawable.ic_volume_up_fill),
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.size(48.dp),
                    )
                }
            }

            Spacer(modifier = Modifier.height(36.dp))

            Text(
                text = stringResource(R.string.play_sound_notification_title, deviceName),
                color = MaterialTheme.colorScheme.onSurface,
                style = MaterialTheme.typography.headlineMedium.copy(
                    fontWeight = FontWeight.SemiBold,
                    lineHeight = 34.sp,
                ),
                textAlign = TextAlign.Center,
            )
        }

        Button(
            onClick = onStop,
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .fillMaxWidth()
                .height(60.dp),
            shape = RoundedCornerShape(18.dp),
            colors = ButtonDefaults.buttonColors(
                containerColor = MaterialTheme.colorScheme.onSurface,
                contentColor = MaterialTheme.colorScheme.surface,
            ),
        ) {
            Text(
                text = stringResource(R.string.play_sound_stop_action),
                style = MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.Bold),
            )
        }
    }
}
