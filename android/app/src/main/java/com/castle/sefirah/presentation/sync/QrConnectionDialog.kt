package com.castle.sefirah.presentation.sync

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import sefirah.common.R
import sefirah.domain.model.ConnectionDetails
import sefirah.domain.model.QrCodeConnectionData
import sefirah.network.util.QrCodeParser

@Composable
fun QrConnectionDialog(
    connectionData: QrCodeConnectionData,
    onDismiss: () -> Unit,
    onConnect: (ConnectionDetails) -> Unit,
) {
    var customIp by remember(connectionData) {
        mutableStateOf(connectionData.addresses.firstOrNull().orEmpty())
    }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = {
            Text(
                text = "Connect to ${connectionData.deviceName}",
                style = MaterialTheme.typography.titleLarge,
            )
        },
        text = {
            Column {
                connectionData.addresses.forEach { ip ->
                    Card(
                        onClick = { customIp = ip },
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = 4.dp),
                        colors = CardDefaults.outlinedCardColors(),
                        shape = MaterialTheme.shapes.medium,
                    ) {
                        Text(
                            text = ip,
                            modifier = Modifier.padding(16.dp),
                            style = MaterialTheme.typography.bodyLarge,
                        )
                    }
                }
                OutlinedTextField(
                    value = customIp,
                    onValueChange = { customIp = it },
                    label = { Text(stringResource(R.string.custom_ip_text_label)) },
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(top = 8.dp),
                    singleLine = true,
                )
            }
        },
        confirmButton = {
            Button(
                enabled = customIp.isNotBlank(),
                onClick = {
                    onConnect(QrCodeParser.toConnectionDetails(connectionData, customIp))
                },
            ) {
                Text(stringResource(R.string.connect_button))
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text(stringResource(R.string.cancel))
            }
        },
    )
}
