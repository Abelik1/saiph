// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.net.Uri
import android.provider.Settings
import android.widget.*
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.*
import net.openid.appauth.AuthorizationResponse
import net.openid.appauth.AuthorizationService
import sefirah.network.orion.HostedApprovalCodes

private val PHONE_PERMISSIONS = listOf(Manifest.permission.READ_SMS, Manifest.permission.SEND_SMS, Manifest.permission.RECEIVE_SMS,
    Manifest.permission.READ_PHONE_STATE, Manifest.permission.ANSWER_PHONE_CALLS, Manifest.permission.CALL_PHONE,
    Manifest.permission.READ_CALL_LOG, Manifest.permission.READ_CONTACTS)

/** A separate preview screen; opening it leaves the setting off. */
class HostedActivity : ComponentActivity() {
    private val lock = AppLock(this)
    private var showingLock = false
    private val runtime by lazy { HostedRuntime.get(this) }
    private val account by lazy { HostedAccount.get(this) }
    private val prefs by lazy { getSharedPreferences("orion_hosted", 0) }
    private lateinit var root: LinearLayout
    private lateinit var status: TextView
    private var saving = ""
    private var poll: Job? = null
    private var deploymentSettings = false
    private val login = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        val response = result.data?.let(AuthorizationResponse::fromIntent)
        if (response == null) message("Sign-in did not complete.") else action { account.complete(response) }
    }
    private val scanRoot = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        result.data?.getStringExtra(OrionQrActivity.HOSTED_ROOT_CODE)?.let(::checkRoot)
    }
    private val sendFile =registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri -> if (uri != null) action { runtime.sendFile(uri) } }
    private val saveFile = registerForActivityResult(ActivityResultContracts.CreateDocument("application/octet-stream")) { uri ->
        if (uri != null && saving.isNotEmpty()) { val id = saving; saving = ""; action { runtime.saveFile(id, uri) } }
    }
    override fun onCreate(state: Bundle?) {
        super.onCreate(state); lock.protectWindow()
        saving = state?.getString("saving") ?: ""; deploymentSettings = state?.getBoolean("deploymentSettings") ?: false
        if (!AppLock.locked(this)) render()
    }
    override fun onSaveInstanceState(state: Bundle) { state.putString("saving", saving); state.putBoolean("deploymentSettings", deploymentSettings); super.onSaveInstanceState(state) }
    override fun onResume() {
        super.onResume()
        if (runtime.enabled() && !sefirah.network.orion.OrionPause.paused(this)) ContextCompat.startForegroundService(this, Intent(this, HostedSyncService::class.java))
        lock.open(::lockedScreen, ::resumeUnlocked)
    }
    private fun resumeUnlocked() {
        if (showingLock || !::status.isInitialized) { showingLock = false; render() }
        UsageAnalytics.opened(this, "hosted")
        UsageAnalytics.ask(this) { render() }
        poll?.cancel()
        poll = lifecycleScope.launch { while (isActive) { status.text = runtime.status + if (account.signedIn()) " · Signed in" else " · Sign in again"; delay(1000) } }
    }
    private fun lockedScreen() {
        if (showingLock) return
        showingLock = true; poll?.cancel()
        root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dp(22), dp(24), dp(22), dp(32)); setBackgroundColor(Palette.BG) }
        setContentView(ScrollView(this).apply { addView(root) })
        root.addView(heading("Saiph is locked")); root.addView(text("Confirm it's you to see Saiph Hosted."))
        root.addView(button("Unlock", true) { lock.declined = false; lock.open({}, ::resumeUnlocked) })
    }
    override fun onPause() { poll?.cancel(); super.onPause() }
    override fun onStop() { lock.stopped(); super.onStop() }
    /** Actions that let another device in need the owner, not just an unlocked phone. */
    private fun verified(reason: String, requireScreenLock: Boolean = true, run: () -> Unit) =
        lock.confirm(reason, requireScreenLock, failure = ::message, success = run)
    private fun message(value: String) = Toast.makeText(this, value, Toast.LENGTH_LONG).show()
    private fun action(run: suspend () -> Unit) {
        lifecycleScope.launch { try { withContext(Dispatchers.IO) { run() }; render() } catch (_: Exception) { message("Hosted could not complete this step. Check sign-in, the root device and your connection, then retry.") } }
    }
    /** Scanned and pasted codes take the same path: nothing is trusted until every fingerprint group is confirmed. */
    private fun checkRoot(value: String) {
        runCatching {
            val inspected = HostedApprovalCodes.inspect(value)
            val fingerprint = HostedApprovalCodes.displayFingerprint(inspected.fingerprint())
            android.app.AlertDialog.Builder(this).setTitle("Compare the full root fingerprint").setMessage("Compare every group with the trusted screen on your computer:\n\n$fingerprint")
                .setNegativeButton("Cancel", null).setPositiveButton("The full fingerprint matches") { _, _ ->
                    verified("Trust your computer as this phone's root device") { action { runtime.enroll(value, fingerprint) } }
                }.show()
        }.onFailure { message("Invalid or expired root code. Ask your computer for a new code.") }
    }
    private fun granted(permission: String) = checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED
    /** Off by default: approved computers may act on texts and calls only after the owner turns this on here. */
    private fun textsAndCalls() {
        root.addView(heading("Texts and calls"))
        root.addView(text("Show your texts and calls on your computers. From any computer approved for your Saiph account you can reply in " +
            "one-to-one conversations, start a new text, answer or decline a ringing call and dial a number, only while this is on. " +
            "If two computers answer or decline the same call, the first one wins and the other is told. " +
            "Texts, numbers and names are end-to-end encrypted; Saiph Hosted cannot read them. Pictures (MMS), group replies and call audio stay on this phone."))
        if (runtime.textsAndCalls()) {
            root.addView(button("Turn off texts and calls") { runtime.setTextsAndCalls(false); render() })
            val missing = PHONE_PERMISSIONS.filterNot(::granted)
            if (missing.isEmpty()) root.addView(text("Android access for messages, calls and contacts is allowed.", 13f, Palette.MUTED))
            else {
                root.addView(text("Some Android access is missing, so your computer shows less. Allow it, or manage it in Android Settings.", 13f, Palette.MUTED))
                root.addView(button("Allow messages and calls access") { requestPermissions(missing.toTypedArray(), 47) })
            }
        } else root.addView(button("Turn on texts and calls") {
            verified("Let your computer send texts and handle calls") {
                runtime.setTextsAndCalls(true)
                PHONE_PERMISSIONS.filterNot(::granted).takeIf { it.isNotEmpty() }?.let { requestPermissions(it.toTypedArray(), 47) }
                render()
            }
        })
    }
    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == 47 && !showingLock) render()
    }
    private fun field(label: String, value: String = ""): EditText { root.addView(text(label)); return EditText(this).apply { setText(value); setTextColor(Palette.TEXT); contentDescription = label; root.addView(this) } }
    private fun render() {
        root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dp(22), dp(24), dp(22), dp(32)); setBackgroundColor(Palette.BG) }
        setContentView(ScrollView(this).apply { addView(root) })
        root.addView(heading("Saiph Hosted preview")); root.addView(text("Activate your beta invitation on the account website first. Use the same account on your phone and computer. Saiph hosts the connection; no server or Tailscale is needed. Your computer approves this phone. Sync stops after 12 hours without renewal from your computer."))
        status = text(runtime.status); root.addView(status)
        if (getSharedPreferences("orion", 0).contains("device_id")) { root.addView(text("This phone is paired with a self-hosted Hub. Use an unpaired phone for Hosted.")); root.addView(button("Back") { finish() }); return }
        if (!runtime.enabled() && !prefs.contains("device_id")) {
            val packagedDefaults = runtime.hasPackagedDefaults()
            if (packagedDefaults) {
                root.addView(text("Connection settings are included in this beta build. Turn on Hosted to continue."))
                root.addView(button(if (deploymentSettings) "Hide advanced connection settings" else "Advanced connection settings") { deploymentSettings = !deploymentSettings; render() })
            }
            if (!packagedDefaults || deploymentSettings) {
                val origin = field("Hosted service address", prefs.getString("origin", "")!!)
                val issuer = field("Sign-in issuer (HTTPS, ending in /)", prefs.getString("issuer", "")!!)
                val audience = field("API audience", prefs.getString("audience", "")!!)
                val client = field("Android native client ID", prefs.getString("client_id", "")!!)
                val refresh = CheckBox(this).apply { text = "Keep me signed in with a protected rotating refresh token"; isChecked = prefs.getBoolean("refresh_tokens", false); setTextColor(Palette.TEXT) }; root.addView(refresh)
                root.addView(button("Save deployment") { verified("Change the Saiph Hosted connection", requireScreenLock = false) {
                    action { runtime.configure(origin.text.toString(), issuer.text.toString(), audience.text.toString(), client.text.toString(), refresh.isChecked) }
                } })
                root.addView(text("Register the native redirect: ${HostedAccount.REDIRECT}"))
            }
        }
        root.addView(button(if (runtime.enabled()) "Turn off Hosted" else "Turn on Hosted") { action {
            val enabled = !runtime.enabled()
            if (enabled) runtime.applyPackagedDefaults()
            runtime.setEnabled(enabled)
            if (enabled) ContextCompat.startForegroundService(this@HostedActivity, Intent(this@HostedActivity, HostedSyncService::class.java)) else stopService(Intent(this@HostedActivity, HostedSyncService::class.java))
        } })
        if (runtime.enabled()) {
            root.addView(heading("Sharing permissions"))
            root.addView(text("Choose only the features you want. Notification access lets Saiph share your phone notifications. Android may restrict clipboard access while Saiph is in the background."))
            fun settings(label: String, target: Intent) { root.addView(button(label) {
                runCatching { startActivity(target) }.onFailure { message("Open Android Settings to manage Saiph permissions.") }
            }) }
            settings("Choose phone notification access", Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
            settings("Saiph connection notifications", Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, packageName))
            settings("Battery and background settings", Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName")))
            if (account.signedIn()) root.addView(button("Sign out") { action { account.signOut() } })
            else root.addView(button("Sign in with your browser") { runCatching {
                val service = AuthorizationService(this)
                try { login.launch(service.getAuthorizationRequestIntent(account.request())) } finally { service.dispose() }
            }.onFailure { message("Could not open sign-in. Check deployment settings.") } })
            if (!prefs.contains("device_id")) {
                root.addView(button("Scan root QR from your computer") { scanRoot.launch(OrionQrActivity.hostedRoot(this)) })
                val code = field("Or paste the root approval code from your computer")
                root.addView(button("Check root code") { checkRoot(code.text.toString()) })
            } else {
                root.addView(text("Your phone's full device fingerprint:\n${runtime.fingerprint}"))
                root.addView(button("Show a fresh device request") { verified("Show a request to add this phone") { action { runtime.freshRequest() } } })
                if (runtime.requestCode.isNotEmpty()) {
                    root.addView(text("Paste this request into the computer, compare this phone's full fingerprint, then approve."))
                    root.addView(EditText(this).apply { setText(runtime.requestCode); setTextColor(Palette.TEXT); isFocusable = false; contentDescription = "Phone device approval request code" })
                }
                textsAndCalls()
                root.addView(button("Choose a file or photo to send") { sendFile.launch(arrayOf("*/*")) })
                root.addView(button("Refresh received files") { render() })
                runtime.offers.forEach { (id, name) -> root.addView(button("Save $name") { saving = id; saveFile.launch(name) }) }
            }
        } else if (prefs.contains("device_id")) root.addView(button("Retire this phone's Hosted identity") {
            android.app.AlertDialog.Builder(this).setTitle("Retire Hosted identity?").setMessage("Revoke this phone on the root computer too. Its encrypted keys and trust history stay on this phone for recovery.")
                .setNegativeButton("Cancel", null).setPositiveButton("Retire") { _, _ -> verified("Retire this phone's Hosted identity", requireScreenLock = false) { action { runtime.retire() } } }.show()
        })
        root.addView(heading("Security"))
        root.addView(lock.toggle())
        UsageAnalytics.settingsViews(this).forEach(root::addView)
        runtime.securityEvents().forEach { root.addView(text(it, 13f, Palette.MUTED)) }
        root.addView(button("Back") { finish() })
    }
}
