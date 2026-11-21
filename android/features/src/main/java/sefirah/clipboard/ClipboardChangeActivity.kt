package sefirah.clipboard

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import androidx.fragment.app.FragmentActivity
import androidx.lifecycle.lifecycleScope
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.launch
import javax.inject.Inject

/**
 * Invisible activity that briefly takes focus so the app can read the clipboard on Android 10+.
 * The clipboard bubble, the home screen's Clipboard action, the quick settings tile and the
 * optional accessibility service all send through it. It runs in its own task, so Saiph's
 * screens stay where they were.
 */
@AndroidEntryPoint
class ClipboardChangeActivity : FragmentActivity() {
    @Inject lateinit var clipboardFeature: ClipboardFeature

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        isRunning = true
        setContentView(
            View(this).apply {
                layoutParams = ViewGroup.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.MATCH_PARENT,
                )
                alpha = 0f
            },
        )
        window.attributes = window.attributes.apply {
            dimAmount = 0f
            flags = flags or
                WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS or
                WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL
        }
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (!hasFocus) return

        lifecycleScope.launch {
            val result = clipboardFeature.sendPrimaryClipboard()
            done?.invoke(result); done = null
            finish()
        }
    }

    override fun onDestroy() {
        isRunning = false
        super.onDestroy()
    }

    companion object {
        @Volatile
        var isRunning: Boolean = false
            private set

        /** Told what the send did; only the launch that asked hears it. */
        @Volatile
        private var done: ((ClipboardSend) -> Unit)? = null

        fun launch(context: Context, result: ((ClipboardSend) -> Unit)? = null) {
            if (isRunning) return
            done = result
            val intent = Intent(context, ClipboardChangeActivity::class.java).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_NO_ANIMATION)
            }
            try { context.startActivity(intent) } catch (_: Exception) { done = null; result?.invoke(ClipboardSend.NOT_SENT) }
        }
    }
}
