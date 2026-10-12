package sefirah.transfer

import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.SystemClock
import androidx.core.app.NotificationCompat
import sefirah.common.R
import sefirah.common.notifications.AppNotifications
import sefirah.common.notifications.NotificationCenter
import sefirah.transfer.util.formatSize

/**
 * Per-transfer notification owned by a send/receive handler.
 * Only mutates/posts notifications; callers format strings.
 */
internal class TransferNotification(
    private val context: Context,
    private val transferId: String,
    private val notificationCenter: NotificationCenter
) {
    private val notificationId = transferId.hashCode()
    private var builder: NotificationCompat.Builder? = null
    private var lastProgressUpdateMs = 0L

    fun showPreparing(title: String) {
        val cancelIntent = Intent().apply {
            setClassName(context.packageName, NETWORK_SERVICE_CLASS)
            action = FileTransferService.ACTION_CANCEL_TRANSFER
            putExtra(FileTransferService.EXTRA_TRANSFER_ID, transferId)
        }
        val cancelPendingIntent = PendingIntent.getService(
            context,
            notificationId,
            cancelIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        builder = notificationCenter.showNotification(
            channelId = AppNotifications.TRANSFER_PROGRESS_CHANNEL,
            notificationId = notificationId
        ) {
            setContentTitle(title)
            setContentText(context.getString(R.string.notification_transfer_preparing))
            setProgress(0, 0, true)
            setOngoing(true)
            setSilent(true)
            setAutoCancel(false)
            addAction(R.drawable.ic_close, context.getString(R.string.cancel), cancelPendingIntent)
        }
    }

    fun updateProgress(
        bytesTransferred: Long,
        totalBytes: Long,
        fileName: String,
        fileIndex: Int,
        fileCount: Int
    ) {
        val current = builder ?: return
        val progress = if (totalBytes > 0) {
            ((bytesTransferred.toFloat() / totalBytes) * 100).toInt()
        } else {
            0
        }
        val now = SystemClock.elapsedRealtime()
        if (progress != 100 && now - lastProgressUpdateMs < PROGRESS_UPDATE_INTERVAL_MS) {
            return
        }
        lastProgressUpdateMs = now

        val fileInfo = if (fileCount > 1) {
            "$fileName ($fileIndex/$fileCount)"
        } else {
            fileName
        }
        val progressText = context.getString(
            R.string.notification_progress_format,
            progress,
            formatSize(bytesTransferred),
            formatSize(totalBytes)
        )

        current.setContentText(fileInfo)
        current.setSubText(progressText)
        current.setProgress(100, progress, false)
        notificationCenter.modifyNotification(current, notificationId) {}
    }

    fun showCompleted(
        fileCount: Int,
        fileUri: Uri? = null,
        mimeType: String? = null
    ) {
        builder = null
        notificationCenter.cancelNotification(notificationId)

        val contentText = if (fileCount > 1) {
            context.getString(R.string.notification_transfer_success_bulk, fileCount)
        } else {
            context.getString(R.string.notification_transfer_success)
        }

        notificationCenter.showNotification(
            channelId = AppNotifications.TRANSFER_COMPLETE_CHANNEL,
            notificationId = notificationId + 1000
        ) {
            setContentTitle(context.getString(R.string.notification_file_transfer_complete))
            setContentText(contentText)
            setOngoing(false)
            setAutoCancel(true)
            setSilent(false)

            if (fileUri != null && mimeType != null) {
                val openIntent = Intent(Intent.ACTION_VIEW).apply {
                    setDataAndType(fileUri, mimeType)
                    flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_GRANT_READ_URI_PERMISSION
                }
                val pendingIntent = PendingIntent.getActivity(
                    context, 0, openIntent,
                    PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
                )
                setContentIntent(pendingIntent)
            }
        }
    }

    fun showError(error: String) {
        builder = null
        notificationCenter.cancelNotification(notificationId)

        notificationCenter.showNotification(
            channelId = AppNotifications.TRANSFER_ERROR_CHANNEL,
            notificationId = notificationId + 2000
        ) {
            setContentTitle(context.getString(R.string.notification_file_transfer_error))
            setContentText(error)
            setOngoing(false)
            setAutoCancel(true)
            setSilent(false)
        }
    }

    fun cancel() {
        builder = null
        notificationCenter.cancelNotification(notificationId)
    }

    companion object {
        private const val NETWORK_SERVICE_CLASS = "sefirah.network.NetworkService"
        private const val PROGRESS_UPDATE_INTERVAL_MS = 500L
    }
}
