package com.orionmini.mobile

import android.Manifest
import android.app.AlertDialog
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.*
import android.provider.Settings
import android.view.View
import android.view.ViewGroup
import android.view.WindowInsets
import android.widget.*
import androidx.activity.ComponentActivity
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.app.NotificationManagerCompat
import androidx.lifecycle.lifecycleScope
import com.castle.sefirah.BuildConfig
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.*
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.json.JSONArray
import org.json.JSONObject
import sefirah.domain.interfaces.NetworkManager
import sefirah.network.orion.*
import sefirah.worker.WorkerManager
import javax.inject.Inject
import java.time.Instant

/** One-time setup, then automatic status and inbox decisions. */
@AndroidEntryPoint
class OrionActivity : ComponentActivity() {
    @Inject lateinit var network: NetworkManager
    @Inject lateinit var link: OrionLink
    @Inject lateinit var worker: WorkerManager
    private lateinit var root: LinearLayout
    private lateinit var navigation: LinearLayout
    private var poll: Job? = null
    private var screen = "home"
    private var lastRender = ""
    private var pairingInProgress = false
    private var computers: List<Pair<String, String>> = emptyList()
    private val prefs by lazy { getSharedPreferences("orion", MODE_PRIVATE) }
    private val lock = AppLock(this)
    private var showingLock = false
    private val updates by lazy { AppUpdates(this) }
    private lateinit var backupSettings: OrionBackupSettings
    private val enrollmentFile = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null && !prefs.contains("device_id")) lifecycleScope.launch {
            val invite = withContext(Dispatchers.IO) { runCatching {
                contentResolver.openInputStream(uri)!!.use { input ->
                    val bytes = ByteArray(16385); var count = 0
                    while (count < bytes.size) { val n = input.read(bytes, count, bytes.size-count); if (n < 0) break; count += n }
                    require(count <= 16384)
                    Enrollment.file(bytes.copyOf(count).toString(Charsets.UTF_8))
                }
            }.getOrNull() }
            if (invite != null) offerInvitation(invite) else {
                pairing(); Toast.makeText(this@OrionActivity, "This invitation is invalid or expired. Ask for a new Saiph invitation.", Toast.LENGTH_LONG).show()
            }
        }
    }
    override fun onCreate(state: Bundle?) {
        super.onCreate(state); Api.migrateMesh(this)
        backupSettings = OrionBackupSettings(this) { if (screen == "advanced") advanced() }
        root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dp(22), dp(24), dp(22), dp(32)) }
        val scroll = ScrollView(this).apply { setBackgroundColor(Palette.BG); addView(root) }
        navigation = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; setPadding(dp(22), dp(12), dp(22), 0) }
        val shell = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; setBackgroundColor(Palette.BG)
            addView(navigation)
            addView(scroll, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
        }
        // Keep navigation visible when the permission list is scrolled or a permission is denied.
        shell.setOnApplyWindowInsetsListener { view, insets ->
            if (Build.VERSION.SDK_INT >= 30) {
                val bars = insets.getInsets(WindowInsets.Type.systemBars()); view.setPadding(0, bars.top, 0, bars.bottom)
            } else {
                @Suppress("DEPRECATION")
                view.setPadding(0, insets.systemWindowInsetTop, 0, insets.systemWindowInsetBottom)
            }
            insets
        }
        setContentView(shell)
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                when (SetupNavigation.back(screen)) {
                    "home" -> leaveForHome()
                    "settings" -> settings()
                    else -> { isEnabled = false; onBackPressedDispatcher.onBackPressed(); isEnabled = true }
                }
            }
        })
        handleQr(intent)
    }
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent); setIntent(intent); handleQr(intent)
        if (intent.getBooleanExtra("setup", false) && prefs.contains("device_id")) setup()
        if (intent.getBooleanExtra("settings", false) && prefs.contains("device_id")) settings()
    }
    private fun handleQr(intent: Intent) {
        val qr = intent.getStringExtra("orion_pairing_qr") ?: intent.data?.takeIf { it.scheme == "orion" }?.toString()
        intent.removeExtra("orion_pairing_qr"); intent.data = null
        qr?.let {
            if (!prefs.contains("device_id")) {
                val invite = runCatching { Enrollment.link(it) }.getOrNull()
                if (invite != null) offerInvitation(invite)
                else Toast.makeText(this, "This invitation is invalid. Ask for a new Saiph invitation.", Toast.LENGTH_LONG).show()
            } else Toast.makeText(this, "This phone is already paired. Its existing server stays configured.", Toast.LENGTH_LONG).show()
        }
    }
    override fun onResume() {
        super.onResume(); network.startService(); lastRender = ""
        lock.protectWindow(AppLock.enabled(this))
        lock.open(::lockedScreen, ::resumeUnlocked)
    }
    override fun onStop() { lock.stopped(); super.onStop() }
    private fun lockedScreen() {
        if (showingLock) return
        showingLock = true; poll?.cancel()
        root.removeAllViews(); navigation.removeAllViews()
        root.addView(heading("Saiph is locked")); root.addView(text("Confirm it's you to open Saiph.", 14f, Palette.MUTED))
        root.addView(buttonRow(button("Unlock", true) { lock.declined = false; lock.open({}, ::resumeUnlocked) }))
    }
    private fun resumeUnlocked() {
        showingLock = false
        updates.checkStartup()
        if (!prefs.contains("device_id")) { pairing(); return }
        val requestedSetup = intent.getBooleanExtra("setup", false)
        intent.removeExtra("setup")
        val requestedSettings = intent.getBooleanExtra("settings", false)
        intent.removeExtra("settings")
        when (SetupNavigation.resume(screen, true, prefs.getBoolean("setup_done", false),
            prefs.getBoolean("setup_deferred", false), requestedSetup, requestedSettings)) {
            "setup" -> setup()
            "settings" -> settings()
            "advanced" -> advanced()
            else -> homeLoop()
        }
    }
    override fun onPause() { poll?.cancel(); super.onPause() }
    private fun title(value: String) {
        root.removeAllViews(); root.addView(heading(value)); navigation.removeAllViews()
        if (!prefs.contains("device_id")) return
        fun action(label: String, run: () -> Unit) {
            navigation.addView(button(label,run=run),LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.WRAP_CONTENT,1f).apply {
                if(navigation.childCount>0)marginStart=dp(8)
            })
        }
        if (screen == "home") action("Settings") { settings() }
        else if (SetupNavigation.offersBack(screen, true)) {
            action("Back to Saiph") { leaveForHome() }
            action(if (screen == "settings") "Permissions" else "Settings") {
                if (screen == "settings") setup() else settings()
            }
        }
    }
    private fun leaveForHome() {
        // Leaving permission setup is separate from marking setup complete.
        if (!prefs.getBoolean("setup_done", false)) prefs.edit().putBoolean("setup_deferred", true).apply()
        intent.removeExtra("setup"); intent.removeExtra("settings"); homeLoop()
    }
    private fun pairing() {
        screen = "pair"; poll?.cancel(); title("Saiph")
        root.addView(button("Saiph Hosted preview") { startActivity(Intent(this, HostedActivity::class.java)) })
        root.addView(text("One system, wherever you are.", 15f, Palette.MUTED)); root.addView(section("Pair once"))
        val invite = pendingEnrollment()
        if (invite != null) {
            root.addView(card().apply {
                addView(text("Your invitation is ready", 16f, bold = true))
                addView(text("Use the official Tailscale app to sign in to the same mesh as your server and accept Android's VPN prompt. Return here when done; Saiph finishes pairing automatically.", 15f))
                if (invite.meshLoginServer != null) {
                    addView(text("This invitation uses a private mesh provider. Advanced setup has its one-time sign-in instructions.", 14f, Palette.MUTED))
                    addView(buttonRow(button("Advanced setup") { meshInstructions(invite) }))
                }
                val installed = tailscaleInstalled()
                addView(buttonRow(button(if (installed) "Open Tailscale" else "Install Tailscale", true) { openTailscale() }))
                addView(text("Pairing continues automatically while this invitation is valid.", 14f, Palette.MUTED))
            })
            val status = text("Waiting for the secure connection…", 14f, Palette.MUTED)
            root.addView(status)
            poll = lifecycleScope.launch {
                while (isActive && !prefs.contains("device_id")) {
                    val current = pendingEnrollment()
                    if (current == null) { pairing(); return@launch }
                    if (!pairingInProgress && tailscaleInstalled()) {
                        pairingInProgress = true
                        val ok = try { withContext(Dispatchers.IO) { runCatching {
                            Api.pair(this@OrionActivity, current.hub, current.code, Build.MODEL, current.meshLoginServer)
                        }.isSuccess } } finally { pairingInProgress = false }
                        if (ok) { network.startService(); setup(); return@launch }
                        status.text = "Waiting for Tailscale. Saiph will keep trying; if this invitation expires, ask for a new one."
                    }
                    delay(3000)
                }
                if (prefs.contains("device_id")) setup()
            }
            return
        }
        root.addView(card().apply {
            addView(text("Scan the one-time QR or open the private invitation from your server or computer. Your phone keeps its own signing key. Use invitations only from a server you trust.", 15f))
            addView(buttonRow(button("Scan pairing QR", true) { startActivity(Intent(this@OrionActivity, OrionQrActivity::class.java)) }))
            addView(buttonRow(button("Open invitation") { enrollmentFile.launch(arrayOf("*/*")) }))
        })
    }
    private fun offerInvitation(invite: Enrollment) {
        if (prefs.contains("device_id") || pairingInProgress) return
        AlertDialog.Builder(this).setTitle("Use this Saiph invitation?")
            .setMessage("Pair this phone with the server that provided this invitation. Continue only if you trust its owner. Your phone keeps its own signing key.")
            .setPositiveButton("Use invitation") { _, _ ->
                // Pairing shares notifications and messages with that server; confirm the owner.
                if (!AppLock.deviceSecure(this)) Toast.makeText(this, "Set a screen lock so nobody else can pair or open this phone.", Toast.LENGTH_LONG).show()
                lock.confirm("Pair this phone with a Saiph server", failure = { Toast.makeText(this, it, Toast.LENGTH_LONG).show() }) { remember(invite) }
            }
            .setNegativeButton("Cancel", null).show()
    }
    private fun remember(invite: Enrollment) {
        if (prefs.contains("device_id") || pairingInProgress) return
        prefs.edit().putString("pending_enrollment", invite.pending(Instant.now()).privateJson()).apply()
        pairing()
    }
    private fun pendingEnrollment(): Enrollment? {
        val value = prefs.getString("pending_enrollment", null) ?: return null
        return runCatching { Enrollment.file(value) }.getOrNull().also {
            if (it == null) prefs.edit().remove("pending_enrollment").apply()
        }
    }
    private fun tailscaleInstalled() = packageManager.getLaunchIntentForPackage("com.tailscale.ipn") != null
    private fun openTailscale() {
        val launch = packageManager.getLaunchIntentForPackage("com.tailscale.ipn")
        if (launch != null) openSettings(launch)
        else {
            val market = Intent(Intent.ACTION_VIEW, Uri.parse("market://details?id=com.tailscale.ipn"))
            try { startActivity(market) } catch (_: Exception) {
                openSettings(Intent(Intent.ACTION_VIEW, Uri.parse("https://play.google.com/store/apps/details?id=com.tailscale.ipn")))
            }
        }
    }
    private fun meshInstructions(invite: Enrollment) {
        AlertDialog.Builder(this).setTitle("Advanced setup")
            .setMessage("Hub: ${invite.hub}\n\nIn the official Tailscale app, open Settings, Accounts, then the three-dot menu and Use an alternate server. Paste the login server below and complete its sign-in and Android VPN consent. Saiph cannot apply this setting for you.\n\nLogin server: ${invite.meshLoginServer}")
            .setPositiveButton("Copy login server") { _, _ ->
                getSystemService(android.content.ClipboardManager::class.java).setPrimaryClip(
                    android.content.ClipData.newPlainText("Mesh login server", invite.meshLoginServer))
            }.setNegativeButton("Close", null).show()
    }
    private fun granted(permission: String) = checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED
    private fun setup() {
        screen = "setup"; poll?.cancel(); title("Make Saiph automatic")
        root.addView(text("Set these once, or finish and return to Settings later. Saiph reconnects automatically.", 15f, Palette.MUTED))
        fun step(label: String, done: Boolean, optional: Boolean = false, manage: (() -> Unit)? = null,
                 partiallyGranted: Boolean = false, action: () -> Unit) {
            root.addView(card().apply {
                addView(text(label, 16f, bold = true))
                addView(text(if (done) "Ready" else if (optional) "Optional · can wait" else "Recommended · can be set later", 13f, Palette.MUTED))
                val actions = mutableListOf<Button>()
                if (!done) actions += button("Set up") { action() }
                if ((done || partiallyGranted) && manage != null) actions += button("Manage") { manage() }
                if (actions.isNotEmpty()) addView(buttonRow(*actions.toTypedArray()))
            })
        }
        root.addView(section("Everyday operation"))
        step("Saiph notifications", getSystemService(android.app.NotificationManager::class.java).areNotificationsEnabled(), manage = {
            openSettings(Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, packageName))
        }) {
            if (Build.VERSION.SDK_INT >= 33) requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 44)
        }
        step("Battery exemption", getSystemService(PowerManager::class.java).isIgnoringBatteryOptimizations(packageName), manage = {
            openSettings(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
        }) {
            openSettings(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName")))
        }
        val connection = text(connectionSummary(), 14f, Palette.MUTED)
        root.addView(card().apply { addView(text("Automatic connection", 16f, bold = true)); addView(connection) })
        // The live mesh handshake proves reachability; an Orion checkbox cannot verify Android's VPN settings.
        poll = lifecycleScope.launch {
            while (isActive) { connection.text = connectionSummary(); delay(1000) }
        }
        root.addView(buttonRow(button("Finish setup", true) {
            prefs.edit().putBoolean("setup_done", true).remove("setup_deferred").apply(); intent.removeExtra("setup"); homeLoop()
        }))
        root.addView(section("Optional features"))
        root.addView(text("These permissions do not block setup. Manage opens Android settings, where you can change or revoke access.", 14f, Palette.MUTED))
        step("Phone notification access", NotificationManagerCompat.getEnabledListenerPackages(this).contains(packageName), optional = true, manage = {
            openSettings(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
        }) {
            openSettings(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
        }
        val phone = arrayOf(Manifest.permission.READ_SMS, Manifest.permission.SEND_SMS, Manifest.permission.RECEIVE_SMS,
            Manifest.permission.READ_PHONE_STATE, Manifest.permission.READ_CALL_LOG, Manifest.permission.READ_CONTACTS, Manifest.permission.ANSWER_PHONE_CALLS,
            Manifest.permission.CALL_PHONE)
        step("Messages and calls", phone.all(::granted), optional = true,
            manage = ::appPermissionSettings, partiallyGranted = phone.any(::granted)) { requestPermissions(phone, 45) }
        val photos = when {
            Build.VERSION.SDK_INT >= 34 -> arrayOf(Manifest.permission.READ_MEDIA_IMAGES, Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED)
            Build.VERSION.SDK_INT >= 33 -> arrayOf(Manifest.permission.READ_MEDIA_IMAGES)
            else -> arrayOf(Manifest.permission.READ_EXTERNAL_STORAGE)
        }
        step("Recent photos", OrionPermissions.read(this).photos, optional = true, manage = {
            if(Build.VERSION.SDK_INT>=30 && Environment.isExternalStorageManager())
                openSettings(Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION,Uri.parse("package:$packageName")))
            else appPermissionSettings()
        }) { requestPermissions(photos, 46) }
        step("Sleep plan and Do Not Disturb sync", getSystemService(android.app.NotificationManager::class.java).isNotificationPolicyAccessGranted, optional = true, manage = {
            openSettings(Intent(Settings.ACTION_NOTIFICATION_POLICY_ACCESS_SETTINGS))
        }) {
            openSettings(Intent(Settings.ACTION_NOTIFICATION_POLICY_ACCESS_SETTINGS))
        }
        step("Background clipboard", worker.isWorkerAlive(), optional = true, manage = {
            openSettings(Intent(Settings.ACTION_APPLICATION_DEVELOPMENT_SETTINGS))
        }) {
            AlertDialog.Builder(this).setTitle("Background clipboard")
                .setMessage("Saiph uses its own bundled worker. Enable Developer options and authorize USB or wireless debugging for your paired computer once. Saiph starts the worker automatically whenever that authorized connection is available. No separate helper app is needed. After a phone reboot, Android may require debugging to be re-enabled; this still needs Samsung testing.")
                .setPositiveButton("Developer settings") { _, _ -> openSettings(Intent(Settings.ACTION_APPLICATION_DEVELOPMENT_SETTINGS)) }
                .setNegativeButton("Later", null).show()
        }
    }
    private fun connectionSummary() = if (link.status.value == "Online") "Ready · connected automatically"
        else "Waiting for connection. Saiph will keep trying automatically; you can finish setup now."

    private fun openSettings(target: Intent) {
        try { startActivity(target) }
        catch (_: Exception) {
            Toast.makeText(this, "This settings page isn't available. Open Android Settings to configure it.", Toast.LENGTH_LONG).show()
        }
    }
    /** Android lets only system apps switch the hotspot on; open its settings page instead. */
    private fun hotspotSettings() {
        val tethering = Intent(Intent.ACTION_MAIN).setClassName("com.android.settings", "com.android.settings.TetherSettings")
        try { startActivity(tethering) } catch (_: Exception) { openSettings(Intent(Settings.ACTION_WIRELESS_SETTINGS)) }
    }
    private fun appPermissionSettings() = openSettings(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName")))

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults); if (screen == "setup") setup()
    }
    private fun homeLoop() {
        screen = "home"; poll?.cancel()
        lastRender = ""; render(null, link.status.value)
        poll = lifecycleScope.launch {
            while (isActive) {
                val items = withContext(Dispatchers.IO) { runCatching { Api.inbox(this@OrionActivity) }.getOrNull() }
                computers = withContext(Dispatchers.IO) { runCatching { OrionComputers.remote(this@OrionActivity) }.getOrDefault(emptyList()) }
                val state = link.status.value; val fingerprint = state + items?.toString() + computers
                if (fingerprint != lastRender) { render(items, state); lastRender = fingerprint }
                delay(5000)
            }
        }
    }
    private fun render(items: JSONArray?, state: String) {
        title("Saiph"); root.addView(text(state, 14f, Palette.MUTED))
        val all = items?.let { a -> (0 until a.length()).map(a::getJSONObject) }.orEmpty()
        root.addView(section("Needs you")); val new = all.filter { it.getString("status") == "new" }
        if (new.isEmpty()) root.addView(card().apply { addView(text(if (items == null) "Your inbox will return automatically." else "All clear", 16f)) })
        new.forEach { root.addView(itemCard(it)) }
        root.addView(section("Recent decisions"))
        all.filter { it.getString("status") != "new" }.take(10).forEach { root.addView(itemCard(it)) }
        root.addView(section("Continuity"))
        root.addView(buttonRow(button("Photo to computer") { startActivity(Intent(this, OrionCaptureActivity::class.java)) }, button("Hotspot settings") { hotspotSettings() }))
        root.addView(buttonRow(button("Remote for computer apps") { startActivity(Intent(this, OrionRemoteActivity::class.java)) }))
        // Opt-in on each computer: Phone remote with "This computer" turned on.
        computers.forEach { (id, name) -> root.addView(buttonRow(button("Lock $name") {
            Toast.makeText(this, if (OrionComputers.lock(link, id)) "Locking $name…" else "Saiph is reconnecting. Nothing was sent.", Toast.LENGTH_SHORT).show()
        })) }
        val wake = runCatching { JSONArray(getSharedPreferences("orion_continuity",0).getString("wake_targets","[]")) }.getOrNull()
        if(wake != null && wake.length()>0) {
            root.addView(section("Computers"))
            for(i in 0 until wake.length()) {
                val target=wake.getString(i)
                root.addView(buttonRow(button("Wake " + target.replace('-', ' ')) {
                    if(link.status.value=="Online" && link.publish("wake",buildJsonObject { put("target",target) })) Toast.makeText(this,"Wake request queued.",Toast.LENGTH_SHORT).show()
                    else Toast.makeText(this,"Saiph is reconnecting. The request has not been sent.",Toast.LENGTH_SHORT).show()
                }))
            }
        }
    }
    private fun itemCard(item: JSONObject): View {
        val kind = item.getString("kind"); val state = item.getString("status"); val open = state == "new"
        return card(strong = open && kind == "proposal").apply {
            if (!open) alpha = 0.7f
            val head = LinearLayout(context).apply { orientation = LinearLayout.HORIZONTAL }
            head.addView(eyebrow(item.optString("source").replace('-', ' ')), LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
            head.addView(text(When.ago(item.optString("created_at")), 12f, Palette.MUTED))
            addView(head)
            addView(text(item.getString("title"), 16f, Palette.TEXT, true).apply { setPadding(0, dp(6), 0, 0) })
            item.optString("body").takeIf { it.isNotBlank() }?.let { addView(text(it, 14f, Palette.MUTED).apply { setPadding(0, dp(4), 0, 0) }) }
            item.optJSONObject("proposal")?.optJSONArray("events")?.let { events ->
                for (i in 0 until events.length()) addView(eventLine(events.getJSONObject(i)))
            }
            item.optJSONObject("proposal")?.optJSONObject("review")?.let { review ->
                addView(text(review.optString("operation") + " · " + review.optString("phone"), 14f, bold = true))
                review.optJSONArray("recipients")?.let { recipients -> addView(text("To: " + (0 until recipients.length()).joinToString(", ") { recipients.getString(it) }, 14f)) }
                if (review.has("app")) addView(text(review.optString("app") + " · " + review.optString("title"), 14f))
                if (review.has("text")) addView(text(review.optString("text"), 15f))
            }
            val link = item.optString("link")
            val buttons = mutableListOf<Button>()
            if (open && kind == "proposal") {
                buttons += button(if (item.optJSONObject("proposal")?.has("action") == true) "Accept" else "Add to calendar", primary = true) { decide(item, "accept") }
                buttons += button("Dismiss") { decide(item, "dismiss") }
            } else if (open) {
                buttons += button("Clear") { decide(item, "done") }
            }
            if (link.startsWith("https://")) buttons += button("Open") { startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(link))) }
            if (buttons.isNotEmpty()) addView(buttonRow(*buttons.toTypedArray()))
            if (!open) addView(text(outcome(item), 13f, Palette.MUTED).apply { setPadding(0, dp(8), 0, 0) })
        }
    }

    private fun eventLine(event: JSONObject) = LinearLayout(this).apply {
        orientation = LinearLayout.HORIZONTAL; setPadding(0, dp(10), 0, 0)
        addView(View(context).apply { background = outline(Palette.DUE, Palette.DUE, 2) },
            LinearLayout.LayoutParams(dp(3), ViewGroup.LayoutParams.MATCH_PARENT).apply { marginEnd = dp(10) })
        val lines = LinearLayout(context).apply { orientation = LinearLayout.VERTICAL }
        lines.addView(text(event.getString("title"), 14f, Palette.TEXT, true))
        val reminders = event.optJSONArray("reminders")?.let { r -> (0 until r.length()).map { When.reminder(r.getInt(it)) } }.orEmpty()
        lines.addView(text(When.event(event.getString("start"), event.optBoolean("all_day")) +
            (if (reminders.isNotEmpty()) " · reminder " + reminders.joinToString(", ") else ""), 13f, Palette.MUTED))
        addView(lines)
    }

    private fun outcome(item: JSONObject): String {
        if (item.optJSONObject("proposal")?.has("action") == true && item.getString("status") == "applied") return "Approved · queued for phone"
        val by = item.optString("decided_by").takeIf { it.isNotBlank() && it != "null" }?.let { " on $it" } ?: ""
        val result = item.optString("result")
        return when (item.getString("status")) {
            "accepted" -> if (result.isNotBlank()) "Accepted$by. Not added yet: $result" else "Accepted$by. Being added to your calendar."
            "applied" -> "In your calendar" + (if (result.isNotBlank()) " · $result" else "")
            "dismissed" -> "Dismissed$by"
            else -> "Cleared$by"
        }
    }

    private fun decide(item: JSONObject, decision: String) = decide(item.getString("id"), decision)
    private fun decide(id: String, decision: String) {
        sendBroadcast(Intent(this, DecisionReceiver::class.java).putExtra("id", id).putExtra("decision", decision))
        Toast.makeText(this, "Saiph will deliver your decision automatically.", Toast.LENGTH_SHORT).show()
    }
    private fun settings() {
        if (screen == "setup" && !prefs.getBoolean("setup_done", false))
            prefs.edit().putBoolean("setup_deferred", true).apply()
        screen = "settings"; poll?.cancel(); title("Settings")
        root.addView(section("Updates"))
        root.addView(text("Saiph ${BuildConfig.VERSION_NAME}. Updates also check automatically.", 14f, Palette.MUTED))
        val updateStatus = text("", 14f, Palette.MUTED)
        val check = button("Check for updates") {}
        check.setOnClickListener { updates.checkManual(check, updateStatus) }
        root.addView(buttonRow(check))
        root.addView(updateStatus)
        root.addView(section("Focus"))
        root.addView(Switch(this).apply {
            text = "Share clipboard across my devices"; isChecked = prefs.getBoolean("clipboard_enabled", true)
            setOnCheckedChangeListener { _, checked -> prefs.edit().putBoolean("clipboard_enabled", checked).apply();network.refreshCapabilities() }
        })
        root.addView(Switch(this).apply {
            text = "Follow the shared sleep plan"; isChecked = prefs.getBoolean("focus_enabled", true)
            setOnCheckedChangeListener { _, checked -> prefs.edit().putBoolean("focus_enabled", checked).apply(); lifecycleScope.launch(Dispatchers.IO) { runCatching { OrionContinuity(this@OrionActivity).tick() } } }
        })
        root.addView(Switch(this).apply {
            text = "Sync Do Not Disturb with my devices"; isChecked = prefs.getBoolean("dnd_sync", true)
            setOnCheckedChangeListener { _, checked -> prefs.edit().putBoolean("dnd_sync", checked).apply(); lifecycleScope.launch(Dispatchers.IO) { runCatching { OrionContinuity(this@OrionActivity).tick() } } }
        })
        root.addView(section("Security"))
        root.addView(lock.toggle())
        root.addView(buttonRow(button("Setup permissions") { setup() }, button("Advanced") { advanced() }))
        root.addView(buttonRow(button("Back to Saiph") { homeLoop() }))
    }
    private fun advanced() {
        screen = "advanced"; poll?.cancel(); title("Advanced")
        root.addView(text("Hub: ${runCatching { Api.base(this) }.getOrDefault("Invalid saved configuration")}\nDevice: ${prefs.getString("device_id", "Unpaired")}\n${BuildConfig.VERSION_NAME} (${BuildConfig.VERSION_CODE})", 14f, Palette.MUTED))
        root.addView(button("Saiph Hosted preview") { startActivity(Intent(this, HostedActivity::class.java)) })
        root.addView(section("Tailscale"))
        root.addView(text("Saiph detects its connection automatically. Android's Always-on VPN setting cannot be verified here. In VPN settings, use Always-on on and Block connections without VPN off; use no exit node.", 14f, Palette.MUTED))
        root.addView(buttonRow(button("VPN settings") { openSettings(Intent(Settings.ACTION_VPN_SETTINGS)) }))
        root.addView(buttonRow(button("Open Tailscale") { openTailscale() }))
        root.addView(backupSettings.view())
        root.addView(buttonRow(button("Back") { settings() }))
    }
}
