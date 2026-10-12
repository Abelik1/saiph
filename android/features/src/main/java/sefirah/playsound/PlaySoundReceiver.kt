package sefirah.playsound

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import dagger.hilt.android.AndroidEntryPoint
import javax.inject.Inject

@AndroidEntryPoint
class PlaySoundReceiver : BroadcastReceiver() {

    @Inject lateinit var playSoundFeature: PlaySoundFeature

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == ACTION_STOP) {
            playSoundFeature.stop(notifyRemote = true)
        }
    }

    companion object {
        const val ACTION_STOP = "sefirah.playsound.PlaySoundReceiver.STOP"
    }
}
