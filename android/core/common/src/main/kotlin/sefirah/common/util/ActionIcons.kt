package sefirah.common.util

import androidx.annotation.DrawableRes
import sefirah.common.R

/**
 * Maps desktop Fluent icon Names to Material Symbols (rounded, fill).
 */
@DrawableRes
fun iconResForAction(icon: String?): Int =
    when (icon) {
        "Accept" -> R.drawable.ic_check
        "Admin" -> R.drawable.ic_admin_panel_settings
        "Airplane" -> R.drawable.ic_flight
        "Apps" -> R.drawable.ic_apps
        "Bluetooth" -> R.drawable.ic_bluetooth
        "Brightness" -> R.drawable.ic_brightness_6
        "Camera" -> R.drawable.ic_photo_camera
        "Cancel" -> R.drawable.ic_cancel
        "Code" -> R.drawable.ic_code
        "CommandPrompt" -> R.drawable.ic_terminal
        "Copy" -> R.drawable.ic_content_copy
        "Cut" -> R.drawable.ic_content_cut
        "Delete" -> R.drawable.ic_delete_fill
        "DeveloperTools" -> R.drawable.ic_build
        "Download" -> R.drawable.ic_download
        "Edit" -> R.drawable.ic_edit
        "Error" -> R.drawable.ic_error
        "FavoriteStar" -> R.drawable.ic_star
        "Folder" -> R.drawable.ic_folder
        "Game" -> R.drawable.ic_sports_esports
        "Globe" -> R.drawable.ic_language
        "Heart" -> R.drawable.ic_favorite
        "Home" -> R.drawable.ic_home_fill
        "Info" -> R.drawable.ic_info_fill
        "KeyboardClassic" -> R.drawable.ic_keyboard
        "SignOut" -> R.drawable.ic_logout
        "LightningBolt" -> R.drawable.ic_bolt
        "Link" -> R.drawable.ic_link
        "Lock" -> R.drawable.ic_lock
        "Mail" -> R.drawable.ic_mail
        "Mute" -> R.drawable.ic_volume_off_fill
        "Paste" -> R.drawable.ic_content_paste
        "Pause" -> R.drawable.ic_pause
        "Phone" -> R.drawable.ic_phone
        "Play" -> R.drawable.ic_play_arrow
        "PowerButton" -> R.drawable.ic_power_settings_new
        "Puzzle" -> R.drawable.ic_extension
        "QuietHours" -> R.drawable.ic_bedtime
        "Recent" -> R.drawable.ic_history
        "Remove" -> R.drawable.ic_remove
        "Save" -> R.drawable.ic_save
        "Search" -> R.drawable.ic_search
        "Settings" -> R.drawable.ic_settings_fill
        "Share" -> R.drawable.ic_share
        "Stop" -> R.drawable.ic_stop
        "Unlock" -> R.drawable.ic_lock_open
        "UpdateRestore" -> R.drawable.ic_restart_alt
        "Upload" -> R.drawable.ic_upload
        "Video" -> R.drawable.ic_videocam
        "Volume" -> R.drawable.ic_volume_up_fill
        "Warning" -> R.drawable.ic_warning
        "Wifi" -> R.drawable.ic_wifi
        else -> R.drawable.ic_info_fill
    }
