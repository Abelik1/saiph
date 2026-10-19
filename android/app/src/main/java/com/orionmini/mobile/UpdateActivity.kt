// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.os.Bundle
import android.view.View
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.castle.sefirah.BuildConfig
import com.google.firebase.appdistribution.FirebaseAppDistribution
import com.google.firebase.appdistribution.UpdateStatus
import kotlinx.coroutines.launch
import com.orionmini.mobile.UpdateController.State

/**
 * Check for updates, then download, verify and hand the update to Android, from the same place
 * this phone already gets Saiph: its Saiph account or its Hub. One main action at a time, with
 * picture steps showing what happens around it. Android always shows its own install prompt.
 */
class UpdateActivity : ComponentActivity() {
    private lateinit var frame: ScreenFrame
    private var shown: Class<*>? = null
    private var progress: ProgressBar? = null
    private var progressText: TextView? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        UpdateController.tidy(this)
        if (UpdateController.state.value.let { it is State.Idle || it is State.Current || it is State.Failed && it.release == null })
            UpdateController.check(this)
        lifecycleScope.launch { repeatOnLifecycle(Lifecycle.State.STARTED) { UpdateController.state.collect { render(it) } } }
    }

    override fun onResume() {
        super.onResume()
        // Back from Android's "Install unknown apps" page: continue with the verified file.
        (UpdateController.state.value as? State.NeedsPermission)?.let {
            if (UpdateInstaller.canInstall(this)) UpdateController.update(this, it.release, it.place)
        }
    }

    private fun render(state: State) {
        if (state is State.Downloading && shown == State.Downloading::class.java) { showProgress(state); return }
        shown = state.javaClass
        frame = ScreenFrame(this, "Update", back = ::finish)
        val root = frame.content
        progress = null; progressText = null
        when (state) {
            State.Idle, State.Checking -> {
                root.addView(status("Checking for updates…", "Saiph ${BuildConfig.VERSION_NAME} is installed."))
                root.addView(ProgressBar(this).apply { isIndeterminate = true; contentDescription = "Checking" })
            }
            is State.Current -> {
                root.addView(status("Saiph is up to date", "Saiph ${state.versionName} (build ${BuildConfig.VERSION_CODE}) is the latest version."))
                frame.dockActions(button("Check again", true) { UpdateController.check(this) })
            }
            is State.Available -> {
                root.addView(status("Update available: ${state.release.versionName}",
                    "Saiph ${BuildConfig.VERSION_NAME} is installed. The update downloads from ${state.place}."))
                notes(root, state.release)
                root.addView(steps(state.place))
                val label = when {
                    state.ready -> "Install update"
                    state.resumable -> "Resume download"
                    else -> "Download and install (${UpdatePolicy.size(state.release.bytes)})"
                }
                frame.dockActions(button(label, true) { UpdateController.update(this, state.release, state.place) })
            }
            is State.AskMetered -> {
                root.addView(status("You're on mobile data",
                    "This update is ${UpdatePolicy.size(state.release.bytes)}. Download it now on mobile data, or connect to Wi-Fi and come back."))
                notes(root, state.release)
                frame.dockActions(button("Download on mobile data", true) { UpdateController.update(this, state.release, state.place, allowMetered = true) })
            }
            is State.NeedsPermission -> {
                root.addView(status("Allow Saiph to install its update",
                    "The update is downloaded and checked. Android asks once before an app can install updates it downloaded. Saiph only installs its own builds, signed like the app you have, and Android still asks before each one."))
                root.addView(stepGuide(Step(StepPicture.ALLOW, "In Android settings, turn on Allow from this source for Saiph."),
                    Step(StepPicture.CONFIRM, "Come back here. Android asks you to confirm the update."),
                    Step(StepPicture.GENUINE, "Saiph restarts on the new version.")))
                frame.dockActions(button("Open Android settings", true) { startActivity(UpdateInstaller.permissionSettings(this)) })
            }
            is State.Downloading -> {
                root.addView(status("Downloading ${state.release.versionName}", "From ${state.place}. You can leave this screen; the download continues."))
                progress = ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal).apply { max = 1000 }
                progressText = text("", UiType.META, Palette.MUTED).apply { accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE }
                root.addView(progress, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(24)))
                root.addView(progressText)
                root.addView(steps(state.place))
                frame.dockActions(button("Pause download") { UpdateController.pause() })
                showProgress(state)
            }
            is State.Verifying -> {
                root.addView(status("Checking the download", "Saiph is making sure this is the published ${state.release.versionName}, signed like the app you have."))
                root.addView(ProgressBar(this).apply { isIndeterminate = true; contentDescription = "Checking" })
            }
            is State.Confirming -> {
                root.addView(status("Confirm in Android", "Android is asking whether to install Saiph ${state.release.versionName}. Saiph closes and reopens on the new version."))
                root.addView(stepGuide(Step(StepPicture.CONFIRM, "Tap Update in Android's prompt."), Step(StepPicture.GENUINE, "Saiph restarts on the new version.")))
                frame.dockActions(button("Show Android's prompt again") { UpdateController.update(this, state.release, state.place) })
            }
            is State.Failed -> {
                root.addView(status("Update not installed", state.message))
                val retry = state.release
                frame.dockActions(button("Try again", true) {
                    if (retry != null && state.place != null) UpdateController.update(this, retry, state.place) else UpdateController.check(this)
                })
                if (state.firebase && BuildConfig.HAS_APP_DISTRIBUTION) firebase(root)
            }
        }
    }

    private fun status(title: String, detail: String) = card().apply {
        addView(cardTitle(title))
        addView(text(detail, UiType.BODY, Palette.MUTED).apply {
            setPadding(0, dp(6), 0, 0); accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
        })
    }

    private fun notes(root: LinearLayout, release: AppRelease) {
        if (release.notes.isNotEmpty()) root.addView(card().apply {
            addView(text("What's new", UiType.BODY, bold = true))
            addView(text(release.notes, UiType.BODY, Palette.MUTED).apply { setPadding(0, dp(6), 0, 0) })
        })
    }

    private fun steps(place: String) = stepGuide(
        Step(StepPicture.DOWNLOAD, "Saiph downloads the update from $place."),
        Step(StepPicture.GENUINE, "Saiph checks it's the published build, signed like the app you have."),
        Step(StepPicture.CONFIRM, "Android asks you to confirm. Saiph restarts updated."))

    private fun showProgress(state: State.Downloading) {
        val total = state.total
        progress?.let { bar ->
            bar.isIndeterminate = total == null
            if (total != null && total > 0) bar.progress = (state.done * 1000 / total).toInt()
        }
        progressText?.text = if (total != null && total > 0) "${state.done * 100 / total}% · ${UpdatePolicy.size(state.done)} of ${UpdatePolicy.size(total)}"
            else "${UpdatePolicy.size(state.done)} downloaded"
    }

    /** Testers who installed through Firebase App Tester can still update there. Never logs SDK or account errors. */
    private fun firebase(root: LinearLayout) {
        val note = text("", UiType.META, Palette.MUTED).apply { accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE }
        val check = compactButton("Check Firebase App Tester") {}
        check.setOnClickListener {
            check.isEnabled = false; note.text = "Checking Firebase App Tester…"
            fun done(message: String) { if (!isDestroyed) { check.isEnabled = true; note.text = message } }
            runCatching {
                FirebaseAppDistribution.getInstance().updateIfNewReleaseAvailable()
                    .addOnProgressListener { progress ->
                        if (!isDestroyed) note.text = when (progress.updateStatus) {
                            UpdateStatus.DOWNLOADING -> "Downloading… Android will ask you to confirm installation."
                            UpdateStatus.NEW_RELEASE_NOT_AVAILABLE -> "Firebase has no newer version."
                            else -> "Preparing update…"
                        }
                    }
                    .addOnSuccessListener { if (note.text != "Firebase has no newer version.") done("Firebase check complete.") }
                    .addOnFailureListener { done("Firebase App Tester is unavailable. Try again later.") }
            }.onFailure { done("Firebase App Tester is unavailable. Try again later.") }
        }
        root.addView(card().apply {
            addView(text("Installed through Firebase App Tester?", UiType.BODY, bold = true))
            addView(text("Firebase can check for its own tester builds.", UiType.META, Palette.MUTED))
            addView(compactActions(check)); addView(note)
        })
    }
}

/** Settings > Version and updates, on both the Saiph account and the Hub settings pages. */
fun android.app.Activity.updateSettings(): List<View> {
    val check = compactButton("Check for updates") { startActivity(android.content.Intent(this, UpdateActivity::class.java)) }
    val automatic = settingSwitch("Check automatically", "Get a notification when an update is published. Saiph never installs one without your confirmation.",
        UpdateNotices.automatic(this)) { _, on -> UpdateNotices.setAutomatic(this, on) }
    return listOf(compactActions(check), automatic.apply { setPadding(0, dp(12), 0, 0) }) + UpdateDebugOverride.controls(this)
}
