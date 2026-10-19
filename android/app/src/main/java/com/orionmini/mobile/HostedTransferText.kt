// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import kotlin.math.ceil
import kotlin.math.floor

/** A refusal the owner can act on; its message is shown as written. */
class TransferRefused(message: String) : IllegalStateException(message)

/** Wording and limits for Saiph Cloud file transfers, shared with the desktop (hosted_transfers.py). */
object HostedTransferText {
    /** Plaintext limit: the relay's 20 MiB ciphertext cap less the 4 KiB the sealed stream may add. */
    const val MAX_PLAINTEXT = 20L * 1024 * 1024 - 4096
    /** Received files go here, as on the desktop: Downloads → Saiph. */
    const val FOLDER = "Saiph"

    fun megabytes(size: Long, up: Boolean = false): String {
        val tenths = size / 1_048_576.0 * 10
        val rounded = (if (up) ceil(tenths) else floor(tenths)) / 10
        return String.format(java.util.Locale.ROOT, "%.1f", rounded)
    }

    fun tooLarge(size: Long) =
        "Saiph Cloud sends files up to ${megabytes(MAX_PLAINTEXT)} MB. This file is ${megabytes(size, up = true)} MB. Nothing was sent."

    fun checkSize(size: Long?) { if (size != null && size > MAX_PLAINTEXT) throw TransferRefused(tooLarge(size)) }

    fun sent(names: List<String>, device: String): String = when (names.size) {
        0 -> "Sent to $device."
        1 -> "Sent ${names[0]} to $device."
        else -> "Sent ${names.size} files to $device."
    }

    fun saved(name: String) = "Saved $name in Downloads → $FOLDER."

    // Files directly over the local network (LanFiles.kt); the desktop's hosted_transfers.py words them the same way.
    fun needsNetwork(size: Long, device: String) =
        "$device didn't answer on your network. Saiph Cloud sends files up to ${megabytes(MAX_PLAINTEXT)} MB and this file is " +
            "${megabytes(size, up = true)} MB, so both devices must be on the same Wi-Fi or network with Saiph open. Nothing was sent."

    fun noNetwork(size: Long) =
        "Saiph Cloud sends files up to ${megabytes(MAX_PLAINTEXT)} MB. This file is ${megabytes(size, up = true)} MB: " +
            "connect this phone to the same Wi-Fi as your computer to send it directly. Nothing was sent."

    fun refused(reason: String, device: String) = when (reason) {
        "storage" -> "$device doesn't have enough free space for this file. Nothing was sent."
        "busy" -> "$device is already receiving several files. Try again when they finish."
        else -> "$device couldn't take this file. Nothing was sent."
    }

    fun failed(code: String, device: String) = when (code) {
        "mismatch" -> "$device received a damaged copy and deleted it. Send it again."
        "lost" -> "The connection to $device was lost for too long. Send it again on the same Wi-Fi."
        "changed" -> "This file changed while it was sending. Send it again."
        else -> "$device stopped receiving this file. Send it again."
    }

    fun sending(name: String, device: String, sent: Long, size: Long, connecting: Boolean) =
        if (connecting) "Connecting to $device on your network…"
        else "Sending $name to $device directly · ${if (size > 0) sent * 100 / size else 100}%"
}
