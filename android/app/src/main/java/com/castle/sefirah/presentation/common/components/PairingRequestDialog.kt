package com.castle.sefirah.presentation.common.components

import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import sefirah.common.R

@Composable
fun PairingRequestDialog(
    deviceName: String,
    verificationCode: String,
    onDismiss: () -> Unit,
    onApprove: () -> Unit,
    onReject: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.pairing_request_title)) },
        text = {
            Text(stringResource(R.string.pairing_request_text, deviceName, verificationCode))
        },
        confirmButton = {
            Button(onClick = onApprove) {
                Text(stringResource(R.string.pairing_request_approve))
            }
        },
        dismissButton = {
            TextButton(onClick = onReject) {
                Text(stringResource(R.string.pairing_request_reject))
            }
        },
    )
}
