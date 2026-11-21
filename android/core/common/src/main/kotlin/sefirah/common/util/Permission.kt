package sefirah.common.util

import android.Manifest
import android.annotation.SuppressLint
import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.os.PowerManager
import android.provider.Settings
import androidx.core.content.getSystemService

data class PermissionStates(
    val notificationGranted: Boolean = false,
    val batteryGranted: Boolean = false,
    val locationGranted: Boolean = false,
    val nearbyDevicesGranted: Boolean = false,
    val overlayGranted: Boolean = false,
    val storageGranted: Boolean = false,
    val accessibilityGranted: Boolean = false,
    val notificationListenerGranted: Boolean = false,
    val readSensitiveNotificationsGranted: Boolean = false,
    val smsPermissionGranted: Boolean = false,
    val contactsGranted: Boolean = false,
    val phoneStateGranted: Boolean = false,
    val callLogsGranted: Boolean = false,
)

fun checkNotificationPermission(
    context: Context,
    onGranted: (String) -> Unit = {}
): Boolean {
    return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
        val granted = context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) ==
                PackageManager.PERMISSION_GRANTED
        if (granted) {
            onGranted(Manifest.permission.POST_NOTIFICATIONS)
        }
        granted
    } else {
        true
    }
}

fun canUseFullScreenAlerts(context: Context): Boolean {
    val permission = Manifest.permission.USE_FULL_SCREEN_INTENT
    return when {
        Build.VERSION.SDK_INT >= 34 -> context.getSystemService<NotificationManager>()?.canUseFullScreenIntent() == true
        Build.VERSION.SDK_INT >= 29 -> context.checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED
        // Before API 29, use the declaration to distinguish apps opting into full-screen alerts.
        else -> context.packageManager.getPackageInfo(context.packageName, PackageManager.GET_PERMISSIONS)
            .requestedPermissions?.contains(permission) == true
    }
}

fun checkBatteryOptimization(context: Context): Boolean {
    return context.getSystemService<PowerManager>()?.isIgnoringBatteryOptimizations(context.packageName)
        ?: false
}

/**
 * Whether this build asks for background location to read trusted Wi-Fi names while Saiph is
 * closed. The Google Play build removes ACCESS_BACKGROUND_LOCATION from its manifest
 * (app/src/play/AndroidManifest.xml) and reads them with foreground location while Saiph is
 * open. The app sets this once from BuildConfig.PLAY_STORE in MainApplication, before anything
 * checks location; the default is the direct build's behaviour.
 */
object LocationPolicy {
    @Volatile var backgroundLocation: Boolean = true
}

/**
 * Whether trusted-network detection has the location access it needs: fine location, plus
 * background location on Android 10 and later when the build asks for it.
 */
fun locationAccessSufficient(fine: Boolean, background: Boolean, sdk: Int, backgroundLocation: Boolean): Boolean =
    fine && (!backgroundLocation || sdk < Build.VERSION_CODES.Q || background)

fun checkLocationPermissions(
    context: Context,
    onGranted: (String) -> Unit = {},
    backgroundLocation: Boolean = LocationPolicy.backgroundLocation,
): Boolean {
    val hasFineLocation = context.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) ==
            PackageManager.PERMISSION_GRANTED
    // Android 9 and below grant background location with foreground location.
    val hasBackgroundLocation = Build.VERSION.SDK_INT < Build.VERSION_CODES.Q ||
        context.checkSelfPermission(Manifest.permission.ACCESS_BACKGROUND_LOCATION) == PackageManager.PERMISSION_GRANTED

    if (hasFineLocation) {
        onGranted(Manifest.permission.ACCESS_FINE_LOCATION)
        onGranted(Manifest.permission.ACCESS_COARSE_LOCATION)
    }
    if (backgroundLocation && hasBackgroundLocation && Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
        onGranted(Manifest.permission.ACCESS_BACKGROUND_LOCATION)
    }

    return locationAccessSufficient(hasFineLocation, hasBackgroundLocation, Build.VERSION.SDK_INT, backgroundLocation)
}

@SuppressLint("InlinedApi")
val NEARBY_DEVICES_PERMISSIONS = arrayOf(
    Manifest.permission.BLUETOOTH_CONNECT,
    Manifest.permission.BLUETOOTH_SCAN,
)

fun nearbyDevicesPermissionGranted(
    context: Context,
    onGranted: (String) -> Unit = {}
): Boolean {
    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) return true

    val allGranted = NEARBY_DEVICES_PERMISSIONS.all {
        context.checkSelfPermission(it) == PackageManager.PERMISSION_GRANTED
    }
    if (allGranted) NEARBY_DEVICES_PERMISSIONS.forEach { onGranted(it) }
    return allGranted
}

fun checkStoragePermission(
    context: Context,
    onGranted: (String) -> Unit = {}
): Boolean {
    return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
        Environment.isExternalStorageManager()
    } else {
        val granted = context.checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE) ==
                PackageManager.PERMISSION_GRANTED
        if (granted) {
            onGranted(Manifest.permission.WRITE_EXTERNAL_STORAGE)
        }
        granted
    }
}

fun openAppSettings(context: Context) {
    val intent = Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS).apply {
        data = Uri.fromParts("package", context.packageName, null)
        addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
    }
    context.startActivity(intent)
}

fun isAccessibilityServiceEnabled(context: Context, accessibilityServiceName: String?): Boolean {
    val enabledServices = Settings.Secure.getString(
        context.contentResolver,
        Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES
    )
    return accessibilityServiceName?.let { enabledServices?.contains(it) } == true
}

fun isNotificationListenerEnabled(context: Context): Boolean {
    val flat = Settings.Secure.getString(
        context.contentResolver,
        "enabled_notification_listeners"
    )
    return flat?.contains(context.packageName) == true
}

fun smsPermissionGranted(
    context: Context,
    onGranted: (String) -> Unit = {}
): Boolean {
    val readSmsPermission = context.checkSelfPermission(Manifest.permission.READ_SMS) ==
        PackageManager.PERMISSION_GRANTED
    val sendSmsPermission = context.checkSelfPermission(Manifest.permission.SEND_SMS) ==
        PackageManager.PERMISSION_GRANTED

    val allGranted = readSmsPermission && sendSmsPermission

    if (allGranted) {
        onGranted(Manifest.permission.READ_SMS)
        onGranted(Manifest.permission.SEND_SMS)
    }

    return allGranted
}

fun isContactsPermissionGranted(context: Context) : Boolean {
    return context.checkSelfPermission(Manifest.permission.READ_CONTACTS) == PackageManager.PERMISSION_GRANTED
}

fun contactsPermissionGranted(
    context: Context,
    onGranted: (String) -> Unit = {}
): Boolean {
    val granted = context.checkSelfPermission(Manifest.permission.READ_CONTACTS) ==
        PackageManager.PERMISSION_GRANTED
    if (granted) {
        onGranted(Manifest.permission.READ_CONTACTS)
    }
    return granted
}

fun phoneStatePermissionGranted(
    context: Context,
    onGranted: (String) -> Unit = {}
): Boolean {
    val phoneStateGranted = context.checkSelfPermission(Manifest.permission.READ_PHONE_STATE) ==
        PackageManager.PERMISSION_GRANTED
    if (phoneStateGranted) {
        onGranted(Manifest.permission.READ_PHONE_STATE)
    }
    return phoneStateGranted
}


fun isCallLogsPermissionGranted(context: Context) : Boolean {
    return context.checkSelfPermission(Manifest.permission.READ_CALL_LOG) == PackageManager.PERMISSION_GRANTED
}
