package sefirah.network.orion

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.os.Environment
import androidx.core.app.NotificationManagerCompat
import sefirah.common.util.phoneStatePermissionGranted
import sefirah.common.util.smsPermissionGranted

object OrionPermissions {
    fun read(context: Context): FeatureAccess {
        fun granted(permission: String) = context.checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED
        val photos = if (Build.VERSION.SDK_INT >= 33)
            granted(Manifest.permission.READ_MEDIA_IMAGES) ||
                (Build.VERSION.SDK_INT >= 34 && granted(Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED))
        else granted(Manifest.permission.READ_EXTERNAL_STORAGE)
        return FeatureAccess(smsPermissionGranted(context), phoneStatePermissionGranted(context),
            granted(Manifest.permission.ANSWER_PHONE_CALLS),
            photos || (Build.VERSION.SDK_INT >= 30 && Environment.isExternalStorageManager()),
            NotificationManagerCompat.getEnabledListenerPackages(context).contains(context.packageName),
            context.getSharedPreferences("orion",0).getBoolean("clipboard_enabled",true))
    }
}
