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
    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dp(22), dp(24), dp(22), dp(32)); setBackgroundColor(Palette.BG) }
        setContentView(ScrollView(this).apply { setBackgroundColor(Palette.BG); addView(root) })
        computers()
        lifecycleScope.launch {
            OrionRemote.result.collect { result ->
                if (result != null && result.source == computer?.first) status.text = if (result.ok) "Done" else result.message
            }
        }
    }
    private fun screen(title: String) {
        watch?.cancel(); root.removeAllViews(); root.addView(heading(title))
        status = text("", 14f, Palette.MUTED); root.addView(status)
    }
    private fun computers() {
        computer = null; screen("Remote")
        status.text = "Finding computers that allow phone remote control…"
        lifecycleScope.launch {
            val own = getSharedPreferences("orion", 0).getString("device_id", null)
            val found = withContext(Dispatchers.IO) { runCatching {
                val devices = JSONObject(Api.request(this@OrionRemoteActivity, "/v1/link/phone")).getJSONArray("devices")
                (0 until devices.length()).map(devices::getJSONObject).filter { device ->
                    val caps = device.optJSONArray("capabilities")
                    device.optBoolean("online") && device.getString("id") != own && caps != null && (0 until caps.length()).any { caps.optString(it) == "remote" }
                }.map { it.getString("id") to it.getString("name") }
            }.getOrNull() }
            when {
                found == null -> status.text = "Saiph is reconnecting. Try again shortly."
                found.isEmpty() -> status.text = "No computer is offering remote control. On your computer open Saiph Settings → Advanced → Phone remote, turn it on and allow this phone."
                found.size == 1 -> { catalog(found.single()); return@launch }
                else -> { status.text = "Choose a computer"; found.forEach { device -> root.addView(button(device.second) { catalog(device) }) } }
            }
            root.addView(button("Back") { finish() })
        }
    }
    private fun catalog(device: Pair<String, String>) {
        computer = device; screen(device.second)
        status.text = "Asking ${device.second} for its apps…"
        if (link.status.value != "Online" || !link.publish("remote.catalog.request", JsonObject(emptyMap()), device.first))
            status.text = "Saiph is reconnecting. Try again shortly."
        val list = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        root.addView(list); root.addView(button("Other computers") { computers() })
        watch = lifecycleScope.launch {
            OrionRemote.catalogs.collect { catalogs ->
                val apps = catalogs[device.first] ?: return@collect
                list.removeAllViews()
                status.text = if (apps.isEmpty()) "No apps are offered. Choose apps in Saiph on your computer." else "Choose an app"
                apps.forEach { remote ->
                    list.addView(button(remote.name + if (remote.available) "" else " · unavailable") { controls(remote) }.apply { isEnabled = remote.available })
                }
            }
        }
    }
    private fun send(remote: RemoteApp, control: RemoteControl, value: String? = null) {
        val device = computer ?: return
        status.text = if (link.status.value == "Online" && link.publish("remote.command", OrionRemote.command(remote.id, control.id, value), device.first))
            "Sending ${control.label}…" else "Saiph is reconnecting. This control has not been sent."
    }
    private fun controls(remote: RemoteApp) {
        screen(remote.name)
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
        root.addView(button("All apps") { computer?.let(::catalog) })
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
            if (link.status.value != "Online") return
            if (moveX != 0 || moveY != 0) link.publish("remote.command", OrionRemote.pad(remote.id, control.id, if (control.id == "scroll") 0 else moveX * 3 / 2, moveY * 3 / 2), device)
            if (click) remote.controls.firstOrNull { it.id == "click" }?.let { link.publish("remote.command", OrionRemote.command(remote.id, it.id), device) }
        }
    }
    override fun onDestroy() { watch?.cancel(); super.onDestroy() }
}
