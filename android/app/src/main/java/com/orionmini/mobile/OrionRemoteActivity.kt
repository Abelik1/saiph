// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.os.Bundle
import android.text.InputFilter
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import kotlin.math.abs
import android.widget.*
import androidx.activity.ComponentActivity
import androidx.lifecycle.lifecycleScope
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.*
import kotlinx.serialization.json.JsonObject
import org.json.JSONObject
import sefirah.network.orion.*
import javax.inject.Inject

/** Choose a computer, then an app from its catalog, and press its fixed controls. */
@AndroidEntryPoint
class OrionRemoteActivity : ComponentActivity() {
    @Inject lateinit var link: OrionLink
    private lateinit var root: LinearLayout
    private lateinit var status: TextView
    private var computer: Pair<String, String>? = null
    private var watch: Job? = null
    /** Where the header arrow and system Back lead from the current page: apps, computers, then out. */
    private var back: () -> Unit = ::finish
    private var choices = 0
    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        onBackPressedDispatcher.addCallback(this, object : androidx.activity.OnBackPressedCallback(true) {
            override fun handleOnBackPressed() = back()
        })
        computers()
        lifecycleScope.launch {
            OrionRemote.result.collect { result ->
                if (result != null && result.source == computer?.first) status.text = if (result.ok) "Done" else result.message
            }
        }
    }
    private fun screen(title: String, back: () -> Unit) {
        watch?.cancel(); this.back = back
        root = ScreenFrame(this, title, back).content
        status = text("", 14f, Palette.MUTED); root.addView(status)
    }
    private fun computers() {
        computer = null; screen("Remote", ::finish)
        status.text = "Finding computers that allow phone remote control…"
        lifecycleScope.launch {
            val found = withContext(Dispatchers.IO) { runCatching { OrionComputers.targets(this@OrionRemoteActivity, "remote") }.getOrNull() }
            when {
                found == null -> { status.text = ""; root.addView(emptyState(com.castle.sefirah.R.drawable.saiph_ic_remote,
                    "Saiph is reconnecting", "Your computers will appear here once this phone is back online.",
                    button("Try again", true) { computers() })) }
                found.isEmpty() -> { status.text = ""; root.addView(emptyState(com.castle.sefirah.R.drawable.saiph_ic_remote,
                    "No computer is offering remote control",
                    "On your computer, open Saiph → Settings → Devices → Phone remote. Turn it on and allow this phone.",
                    button("Try again", true) { computers() })) }
                found.size == 1 -> { choices = 1; catalog(found.single()); return@launch }
                else -> { choices = found.size; status.text = "Choose a computer"
                    root.addView(settingsList(found.map { device -> settingsRow(sefirah.common.R.drawable.ic_desktop_windows, device.second, null) { catalog(device) } })) }
            }
        }
    }
    private fun catalog(device: Pair<String, String>) {
        computer = device; screen(device.second, back = { if (choices > 1) computers() else finish() })
        status.text = "Asking ${device.second} for its apps…"
        if (!OrionComputers.send(this, link, device.first, "remote.catalog.request", JsonObject(emptyMap())))
            status.text = "Saiph is reconnecting. Try again shortly."
        val list = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        root.addView(list)
        watch = lifecycleScope.launch {
            OrionRemote.catalogs.collect { catalogs ->
                val apps = catalogs[device.first] ?: return@collect
                list.removeAllViews()
                status.text = if (apps.isEmpty()) "" else "Choose an app"
                if (apps.isEmpty()) list.addView(emptyState(com.castle.sefirah.R.drawable.saiph_ic_remote, "No apps are offered yet",
                    "On ${device.second}, open Saiph → Settings → Devices → Phone remote and choose the apps this phone may control."))
                apps.forEach { remote ->
                    list.addView(button(remote.name + if (remote.available) "" else " · unavailable") { controls(remote) }.apply { isEnabled = remote.available })
                }
            }
        }
    }
    private fun send(remote: RemoteApp, control: RemoteControl, value: String? = null) {
        val device = computer ?: return
        status.text = if (OrionComputers.send(this, link, device.first, "remote.command", OrionRemote.command(remote.id, control.id, value)))
            "Sending ${control.label}…" else "Saiph is reconnecting. This control has not been sent."
    }
    private fun controls(remote: RemoteApp) {
        screen(remote.name, back = { computer?.let(::catalog) ?: computers() })
        status.text = "Controls go to ${computer?.second}."
        remote.controls.filter { it.kind == "text" }.forEach { control ->
            val input = field(control.label).apply { filters = arrayOf(InputFilter.LengthFilter(control.max)); isSingleLine = true }
            root.addView(input)
            root.addView(buttonRow(button("Send text", true) {
                val value = input.text.toString()
                if (value.isNotBlank()) { send(remote, control, value); input.setText("") }
            }))
        }
        // Touchpad surfaces: movement is batched about every 30 ms; a quick tap clicks.
        val pads = remote.controls.filter { it.kind == "pad" }.map { control ->
            Pad(control).also { root.addView(it, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(if (control.id == "scroll") 72 else 260)).apply { bottomMargin = dp(10) }) }
        }
        if (pads.isNotEmpty()) watch = lifecycleScope.launch {
            while (isActive) {
                pads.forEach { pad -> pad.flush(remote) }
                delay(30)
            }
        }
        // Two buttons per row: a simple table of the app's controls.
        remote.controls.filter { it.kind == "button" }.chunked(2).forEach { pair ->
            root.addView(buttonRow(*pair.map { control -> button(control.label) { send(remote, control) } }.toTypedArray()))
        }
    }
    private inner class Pad(val control: RemoteControl) : View(this@OrionRemoteActivity) {
        private var lastX = 0f; private var lastY = 0f; private var dx = 0f; private var dy = 0f
        private var downAt = 0L; private var travelled = 0f; private var tapped = false
        init { background = outline(Palette.FIELD, Palette.LINE, 12); contentDescription = control.label }
        override fun onTouchEvent(event: MotionEvent): Boolean {
            when (event.actionMasked) {
                MotionEvent.ACTION_DOWN -> { lastX = event.x; lastY = event.y; downAt = event.eventTime; travelled = 0f; parent.requestDisallowInterceptTouchEvent(true) }
                MotionEvent.ACTION_MOVE -> {
                    val stepX = event.x - lastX; val stepY = event.y - lastY
                    synchronized(this) { dx += stepX; dy += stepY }
                    travelled += abs(stepX) + abs(stepY); lastX = event.x; lastY = event.y
                }
                MotionEvent.ACTION_UP -> if (control.id == "move" && travelled < 12 && event.eventTime - downAt < 250) synchronized(this) { tapped = true }
            }
            return true
        }
        fun flush(remote: RemoteApp) {
            val device = computer?.first ?: return
            val (moveX, moveY, click) = synchronized(this) { Triple(dx.toInt(), dy.toInt(), tapped).also { dx -= it.first; dy -= it.second; tapped = false } }
            if (moveX != 0 || moveY != 0) OrionComputers.send(this@OrionRemoteActivity, link, device, "remote.command", OrionRemote.pad(remote.id, control.id, if (control.id == "scroll") 0 else moveX * 3 / 2, moveY * 3 / 2))
            if (click) remote.controls.firstOrNull { it.id == "click" }?.let { OrionComputers.send(this@OrionRemoteActivity, link, device, "remote.command", OrionRemote.command(remote.id, it.id)) }
        }
    }
    override fun onDestroy() { watch?.cancel(); super.onDestroy() }
}
