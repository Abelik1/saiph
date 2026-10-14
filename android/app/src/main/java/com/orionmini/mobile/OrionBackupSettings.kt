package com.orionmini.mobile

import android.app.AlertDialog
import android.content.Context
import android.content.Intent
import android.widget.LinearLayout
import android.widget.Switch
import android.widget.Toast
import android.widget.ScrollView
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import java.text.DateFormat
import java.util.Date

/** Register before Activity STARTED; the system folder picker grants access once. */
class OrionBackupSettings(private val activity: ComponentActivity, private val changed: () -> Unit) {
    private val preferences = activity.getSharedPreferences("orion_backup", Context.MODE_PRIVATE)
    private val picker = activity.registerForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri ->
        if (uri != null) {
            try {
                activity.contentResolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION)
                val folders = preferences.getStringSet("folders", emptySet()).orEmpty().toMutableSet()
                folders.add(uri.toString()); preferences.edit().putStringSet("folders", folders).apply()
                OrionBackupWorker.schedule(activity)
            } catch (_: Exception) {
                Toast.makeText(activity, "This folder cannot be kept for automatic backups. Choose a local folder.", Toast.LENGTH_LONG).show()
            }
            changed()
        }
    }

    fun view() = LinearLayout(activity).apply {
        orientation = LinearLayout.VERTICAL
        addView(activity.section("Automatic backups"))
        addView(Switch(activity).saiph().apply {
            text = "Back up Saiph received files and selected folders"; isChecked = preferences.getBoolean("enabled", true)
            setOnCheckedChangeListener { _, enabled -> preferences.edit().putBoolean("enabled", enabled).apply(); OrionBackupWorker.schedule(activity) }
        })
        addView(activity.text("Runs daily while charging, using unmetered network by default. Android only allows Saiph's own received files and folders you grant here; other apps' private data and Saiph's credentials are excluded.", 14f, Palette.MUTED))
        addView(Switch(activity).saiph().apply {
            text = "Allow backup over mobile data"; isChecked = preferences.getBoolean("mobile_data", false)
            setOnCheckedChangeListener { _, enabled -> preferences.edit().putBoolean("mobile_data", enabled).apply(); OrionBackupWorker.schedule(activity) }
        })
        val last = preferences.getLong("last_success", 0)
        val state = when (preferences.getString("state", "waiting")) {
            "ready" -> "Last completed: " + DateFormat.getDateTimeInstance().format(Date(last)) + " · ${preferences.getLong("files", 0)} files"
            "running" -> "Backing up automatically"
            "permission" -> "A selected folder needs permission again. Remove it and select it once more."
            "storage" -> "Waiting for enough free phone storage to stage selected content."
            else -> "Waiting for charging and network. Connection failures retry automatically."
        }
        addView(activity.text(state, 14f, Palette.MUTED))
        addView(activity.buttonRow(activity.button("Choose backup folder") { picker.launch(null) }))
        val folders = preferences.getStringSet("folders", emptySet()).orEmpty().toSet()
        folders.forEachIndexed { index, uri ->
            addView(activity.buttonRow(activity.button("Remove folder ${index + 1}") {
                preferences.edit().putStringSet("folders", folders - uri).apply()
                runCatching { activity.contentResolver.releasePersistableUriPermission(android.net.Uri.parse(uri), Intent.FLAG_GRANT_READ_URI_PERMISSION) }
                changed()
            }))
        }
        addView(activity.text("Bundled restic 0.19.1 (BSD 2-Clause). Android runtime: ResticDroid, GPL v3 or later. Licenses are bundled in Saiph; matching source is provided with the release artifacts.", 13f, Palette.MUTED))
        addView(activity.buttonRow(activity.button("Backup licenses") {
            val licenseIds = listOf(io.github.resticdroid.restic.R.raw.resticdroid_notice,
                io.github.resticdroid.restic.R.raw.restic_license,
                io.github.resticdroid.restic.R.raw.resticdroid_license)
            val licenses = licenseIds.joinToString("\n\n") { id ->
                activity.resources.openRawResource(id).bufferedReader().use { it.readText() }
            }
            val content = ScrollView(activity).apply { addView(activity.text(licenses, 13f)) }
            AlertDialog.Builder(activity).setTitle("Backup licenses").setView(content)
                .setPositiveButton("Close", null).show()
        }))
    }
}
