// SPDX-License-Identifier: GPL-3.0-only
package sefirah.network.orion

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.WallpaperManager
import android.bluetooth.BluetoothManager
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.Canvas
import android.media.AudioManager
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.wifi.SupplicantState
import android.net.wifi.WifiManager
import android.os.BatteryManager
import android.os.Build
import android.os.Environment
import android.provider.Settings
import android.telephony.TelephonyManager
import androidx.core.app.NotificationCompat
import java.io.ByteArrayOutputStream

/**
 * Reads the phone's status and runs its quick actions, for the self-hosted Hub
 * and Saiph Cloud alike: local system services only, no polling of its own, no
 * location (so no Wi-Fi name) and no phone-state permission. Each transport's
 * sync loop calls [read] on its existing cadence.
 */
object PhoneQuickControls {
    private const val HOTSPOT_NOTIFICATION = 46

    /** The owner's "Status and quick controls" switch, one for both transports. On by default. */
    fun shared(context: Context) = context.getSharedPreferences("orion_hosted", 0).getBoolean("status_shared", true)
    fun setShared(context: Context, value: Boolean) = check(context.getSharedPreferences("orion_hosted", 0).edit().putBoolean("status_shared", value).commit())

    /** Quick actions this phone accepts now over [transport]. */
    fun controls(context: Context, transport: PhoneTransport): List<String> =
        PhoneStatusFrames.controls(shared(context), policyAccess(context), OrionPermissions.read(context).notifications,
            wallpaperReadable(context), transport)

    /** The current status as [transport] carries it: hidden while the owner has turned sharing off. */
    fun current(context: Context, transport: PhoneTransport, mobileData: Boolean, paused: Boolean): PhoneStatus =
        if (!shared(context)) PhoneStatusFrames.hidden(mobileData, paused) else read(context, controls(context, transport), mobileData, paused)

    /**
     * Runs a quick action that needs only this phone's system services. Status,
     * media, wallpaper and mobile data belong to the transport and return false.
     */
    fun apply(context: Context, command: PhoneControlCommand): Boolean {
        when (command) {
            PhoneControlCommand.Ring -> OrionRing.start(context)
            PhoneControlCommand.RingStop -> OrionRing.stop(context)
            is PhoneControlCommand.Ringer -> setRinger(context, command.mode)
            is PhoneControlCommand.Dnd -> setDnd(context, command.active)
            PhoneControlCommand.Hotspot -> offerHotspot(context)
            else -> return false
        }
        return true
    }

    fun read(context: Context, controls: List<String>, mobileData: Boolean, paused: Boolean): PhoneStatus {
        val battery = context.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        val level = battery?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) ?: -1
        val scale = battery?.getIntExtra(BatteryManager.EXTRA_SCALE, 100)?.takeIf { it > 0 } ?: 100
        val state = battery?.getIntExtra(BatteryManager.EXTRA_STATUS, -1)
        val connectivity = context.getSystemService(ConnectivityManager::class.java)
        val network = runCatching { connectivity.getNetworkCapabilities(connectivity.activeNetwork) }.getOrNull()
        val audio = context.getSystemService(AudioManager::class.java)
        val notifications = context.getSystemService(NotificationManager::class.java)
        val filter = runCatching { notifications.currentInterruptionFilter }.getOrDefault(NotificationManager.INTERRUPTION_FILTER_UNKNOWN)
        return PhoneStatus(
            battery = if (level >= 0) level * 100 / scale else null,
            charging = state == BatteryManager.BATTERY_STATUS_CHARGING || state == BatteryManager.BATTERY_STATUS_FULL,
            wifi = network?.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) == true,
            cellular = network?.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) == true,
            metered = runCatching { connectivity.isActiveNetworkMetered }.getOrDefault(true),
            bluetooth = runCatching { context.getSystemService(BluetoothManager::class.java)?.adapter?.isEnabled }.getOrNull(),
            signal = cellularLevel(context),
            ringer = runCatching { PhoneFeatureFrames.ringer(audio.ringerMode) }.getOrNull(),
            dnd = if (filter == NotificationManager.INTERRUPTION_FILTER_UNKNOWN) null else filter != NotificationManager.INTERRUPTION_FILTER_ALL,
            controls = controls, mobileData = mobileData, paused = paused,
            wifiLevel = wifiLevel(context, network), cellularLevel = cellularLevel(context),
        )
    }

    /**
     * Mobile bars 0-4 from the default SIM, whichever network is active (Android's
     * status bar shows them while on Wi-Fi too). Null without a ready SIM, without
     * a registered cell (Android 10+), or before Android 9.
     */
    private fun cellularLevel(context: Context): Int? = runCatching {
        if (Build.VERSION.SDK_INT < 28) return null
        val telephony = context.getSystemService(TelephonyManager::class.java) ?: return null
        if (telephony.simState != TelephonyManager.SIM_STATE_READY) return null
        val strength = telephony.signalStrength ?: return null
        if (Build.VERSION.SDK_INT >= 29 && strength.cellSignalStrengths.isEmpty()) return null
        strength.level.coerceIn(0, 4)
    }.getOrNull()

    /**
     * Wi-Fi bars 0-4 from the connection's RSSI, computed the way Android's status
     * bar does; null when Wi-Fi is not connected. No location access is needed.
     */
    private fun wifiLevel(context: Context, network: NetworkCapabilities?): Int? = runCatching {
        val wifi = context.applicationContext.getSystemService(WifiManager::class.java) ?: return null
        var rssi: Int? = null
        if (Build.VERSION.SDK_INT >= 29 && network?.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) == true)
            rssi = network.signalStrength.takeIf { it != NetworkCapabilities.SIGNAL_STRENGTH_UNSPECIFIED }
        if (rssi == null) {
            @Suppress("DEPRECATION") val info = wifi.connectionInfo ?: return null
            if (info.supplicantState != SupplicantState.COMPLETED || info.rssi <= -127) return null
            rssi = info.rssi
        }
        if (Build.VERSION.SDK_INT >= 30) PhoneStatusFrames.bars(wifi.calculateSignalLevel(rssi), wifi.maxSignalLevel)
        else @Suppress("DEPRECATION") WifiManager.calculateSignalLevel(rssi, 5)
    }.getOrNull()

    /** True on a metered network such as mobile data; the Cloud sync pauses there when the owner said so. */
    fun metered(context: Context): Boolean = runCatching {
        context.getSystemService(ConnectivityManager::class.java).isActiveNetworkMetered
    }.getOrDefault(false)

    fun policyAccess(context: Context): Boolean =
        runCatching { context.getSystemService(NotificationManager::class.java).isNotificationPolicyAccessGranted }.getOrDefault(false)

    /** Android lets an ordinary app read the wallpaper only with All files access (13+) or storage access (12 and older). */
    fun wallpaperReadable(context: Context): Boolean =
        if (Build.VERSION.SDK_INT >= 33) Environment.isExternalStorageManager()
        else context.checkSelfPermission(Manifest.permission.READ_EXTERNAL_STORAGE) == PackageManager.PERMISSION_GRANTED ||
            (Build.VERSION.SDK_INT >= 30 && Environment.isExternalStorageManager())

    /** A small JPEG of the home-screen wallpaper (at most 384 pixels a side, 12,000 bytes); null when unreadable. */
    @Suppress("MissingPermission")
    fun wallpaper(context: Context): ByteArray? = runCatching {
        if (!wallpaperReadable(context)) return null
        val drawable = WallpaperManager.getInstance(context).drawable ?: return null
        val width = drawable.intrinsicWidth.takeIf { it > 0 } ?: 1080
        val height = drawable.intrinsicHeight.takeIf { it > 0 } ?: 1920
        var side = 384
        while (side >= 96) {
            val scale = side.toFloat() / maxOf(width, height)
            val bitmap = Bitmap.createBitmap(maxOf(1, (width * scale).toInt()), maxOf(1, (height * scale).toInt()), Bitmap.Config.ARGB_8888)
            drawable.setBounds(0, 0, bitmap.width, bitmap.height)
            drawable.draw(Canvas(bitmap))
            for (quality in intArrayOf(70, 50, 35)) {
                val out = ByteArrayOutputStream()
                bitmap.compress(Bitmap.CompressFormat.JPEG, quality, out)
                if (out.size() <= 12_000) { bitmap.recycle(); return out.toByteArray() }
            }
            bitmap.recycle()
            side = side * 3 / 4
        }
        null
    }.getOrNull()

    fun setRinger(context: Context, mode: String) {
        check(policyAccess(context))
        context.getSystemService(AudioManager::class.java).ringerMode = PhoneFeatureFrames.ringerMode(mode)
    }

    /** The phone's own Do Not Disturb, as Phone Link's toggle does; priority only, never total silence. */
    fun setDnd(context: Context, active: Boolean) {
        val manager = context.getSystemService(NotificationManager::class.java)
        check(manager.isNotificationPolicyAccessGranted)
        manager.setInterruptionFilter(if (active) NotificationManager.INTERRUPTION_FILTER_PRIORITY else NotificationManager.INTERRUPTION_FILTER_ALL)
    }

    /**
     * Android does not let ordinary apps switch the hotspot on. The computer can
     * ask for a notification that opens the phone's hotspot settings in one tap.
     */
    fun offerHotspot(context: Context) {
        val tether = Intent("android.settings.TETHER_SETTINGS").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        val target = if (tether.resolveActivity(context.packageManager) != null) tether
            else Intent(Settings.ACTION_WIRELESS_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        val manager = context.getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel("orion_hotspot", "Hotspot requests", NotificationManager.IMPORTANCE_HIGH))
        val open = PendingIntent.getActivity(context, HOTSPOT_NOTIFICATION, target, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        runCatching {
            manager.notify(HOTSPOT_NOTIFICATION, NotificationCompat.Builder(context, "orion_hotspot").setSmallIcon(android.R.drawable.stat_sys_upload)
                .setContentTitle("Your computer wants to use your hotspot").setContentText("Tap to open hotspot settings and turn it on.")
                .setContentIntent(open).setAutoCancel(true).setTimeoutAfter(120_000).setPriority(NotificationCompat.PRIORITY_HIGH).build())
        }
    }
}
