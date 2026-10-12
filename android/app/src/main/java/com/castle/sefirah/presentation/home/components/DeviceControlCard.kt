package com.castle.sefirah.presentation.home.components

import android.graphics.BitmapFactory
import android.util.Base64
import androidx.compose.animation.animateContentSize
import androidx.compose.foundation.Image
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.ripple
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import sefirah.common.R
import sefirah.common.util.iconResForAction
import sefirah.domain.model.ActionInfo
import sefirah.presentation.components.Button
import sefirah.presentation.components.TextButton


@Composable
fun DeviceControlCard(
    actions: List<ActionInfo>,
    onActionClick: (ActionInfo) -> Unit,
    modifier: Modifier = Modifier,
    showLabels: Boolean = true,
) {
    var showDialog by remember { mutableStateOf(false) }
    var selectedAction by remember { mutableStateOf<ActionInfo?>(null) }
    var expanded by remember { mutableStateOf(false) }

    if (showDialog && selectedAction != null) {
        ActionConfirmationDialog(
            actionName = selectedAction!!.actionName,
            onConfirm = {
                onActionClick(selectedAction!!)
                showDialog = false
                selectedAction = null
            },
            onDismiss = {
                showDialog = false
                selectedAction = null
            }
        )
    }

    Card(
        modifier = modifier.fillMaxWidth()
    ) {
        Column(
            modifier = Modifier.animateContentSize()
        ) {
            Column(
                modifier = Modifier.padding(top = 16.dp, bottom = if (actions.size > 5) 0.dp else 16.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                val itemsToShow = if (expanded || actions.size <= 5) actions else actions.take(5)
                itemsToShow.chunked(5).forEach { rowActions ->
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 8.dp)
                    ) {
                        for (i in 0 until 5) {
                            Box(
                                modifier = Modifier.weight(1f),
                                contentAlignment = Alignment.Center
                            ) {
                                if (i < rowActions.size) {
                                    val action = rowActions[i]
                                    val customBitmap = remember(action.actionId, action.icon) {
                                        decodeIconIfCustom(action.icon)
                                    }
                                    DeviceControlButton(
                                        iconRes = if (customBitmap == null) iconResForAction(action.icon) else null,
                                        iconBitmap = customBitmap,
                                        name = action.actionName,
                                        showLabel = showLabels,
                                        onClick = {
                                            if (action.askForConfirmation) {
                                                selectedAction = action
                                                showDialog = true
                                            } else {
                                                onActionClick(action)
                                            }
                                        },
                                    )
                                }
                            }
                        }
                    }
                }
            }

            if (actions.size > 5) {
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable(
                            interactionSource = remember { MutableInteractionSource() },
                            indication = null
                        ) { expanded = !expanded }
                        .padding(bottom = 8.dp),
                    contentAlignment = Alignment.Center
                ) {
                    Icon(
                        painter = painterResource(
                            if (expanded) R.drawable.ic_keyboard_arrow_up else R.drawable.ic_keyboard_arrow_down
                        ),
                        contentDescription = if (expanded) "Show less" else "Show more"
                    )
                }
            }
        }
    }
}

private fun decodeIconIfCustom(icon: String?): ImageBitmap? {
    // Built-in Fluent Names are short; custom icons arrive as base64.
    if (icon.isNullOrBlank() || icon.length < 64) return null
    return runCatching {
        val bytes = Base64.decode(icon, Base64.DEFAULT)
        BitmapFactory.decodeByteArray(bytes, 0, bytes.size)?.asImageBitmap()
    }.getOrNull()
}

@Composable
fun DeviceControlButton(
    name: String,
    onClick: () -> Unit,
    iconRes: Int? = null,
    iconBitmap: ImageBitmap? = null,
    showLabel: Boolean = true,
    color: Color = MaterialTheme.colorScheme.primary,
) {
    val interactionSource = remember { MutableInteractionSource() }
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 2.dp, vertical = 4.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(4.dp)
    ) {
        Box(
            modifier = Modifier
                .size(40.dp)
                .clickable(
                    interactionSource = interactionSource,
                    indication = ripple(bounded = false, radius = 20.dp),
                    onClick = onClick,
                ),
            contentAlignment = Alignment.Center,
        ) {
            when {
                iconBitmap != null -> Image(
                    bitmap = iconBitmap,
                    contentDescription = name,
                    modifier = Modifier.size(24.dp),
                    contentScale = ContentScale.Fit
                )
                iconRes != null -> Icon(
                    painter = painterResource(iconRes),
                    contentDescription = name,
                    tint = color,
                    modifier = Modifier.size(24.dp),
                )
                else -> Icon(
                    painter = painterResource(iconResForAction(null)),
                    contentDescription = name,
                    tint = color,
                    modifier = Modifier.size(24.dp),
                )
            }
        }
        if (showLabel) {
            Text(
                text = name,
                style = MaterialTheme.typography.bodySmall,
                textAlign = TextAlign.Center,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier
                    .fillMaxWidth()
                    .clickable(
                        interactionSource = interactionSource,
                        indication = null,
                        onClick = onClick,
                    ),
            )
        }
    }
}

@Composable
fun TimerDialog(
    title: String,
    hours: String,
    minutes: String,
    seconds: String,
    onHoursChange: (String) -> Unit,
    onMinutesChange: (String) -> Unit,
    onSecondsChange: (String) -> Unit,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Set timer for $title") },
        text = {
            Column {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceEvenly,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    OutlinedTextField(
                        value = hours,
                        onValueChange = { onHoursChange(it.filter { char -> char.isDigit() }) },
                        label = { Text("Hours") },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        modifier = Modifier.weight(1f)
                    )

                    Spacer(modifier = Modifier.width(8.dp))

                    OutlinedTextField(
                        value = minutes,
                        onValueChange = { onMinutesChange(it.filter { char -> char.isDigit() }) },
                        label = { Text("Minutes") },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        modifier = Modifier.weight(1f)
                    )

                    Spacer(modifier = Modifier.width(8.dp))

                    OutlinedTextField(
                        value = seconds,
                        onValueChange = { onSecondsChange(it.filter { char -> char.isDigit() }) },
                        label = { Text("Seconds") },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        modifier = Modifier.weight(1f)
                    )
                }
            }
        },
        confirmButton = {
            Button(onClick = onConfirm) {
                Text("Confirm")
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text("Cancel")
            }
        }
    )
}

@Composable
fun ActionConfirmationDialog(
    actionName: String,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Confirm Action") },
        text = { Text("Are you sure you want to perform the action: $actionName?") },
        confirmButton = {
            Button(onClick = onConfirm) {
                Text("Confirm")
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text("Cancel")
            }
        }
    )
}
