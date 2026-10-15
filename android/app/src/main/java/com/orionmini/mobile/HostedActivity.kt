// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.Manifest
import android.content.Intent
import android.content.ActivityNotFoundException
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
import net.openid.appauth.AppAuthConfiguration
import sefirah.network.orion.HostedApprovalCodes

private val PHONE_PERMISSIONS = listOf(Manifest.permission.READ_SMS, Manifest.permission.SEND_SMS, Manifest.permission.RECEIVE_SMS,
    Manifest.permission.READ_PHONE_STATE, Manifest.permission.ANSWER_PHONE_CALLS, Manifest.permission.CALL_PHONE,
    Manifest.permission.READ_CALL_LOG, Manifest.permission.READ_CONTACTS)

/** Account sign-in first; choosing Sign in applies this build's public defaults. */
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
    private var signingIn = false
    private var shownWaiting = false
    private var loginState: String? = null
    private var loginError = ""
    private var authorizationService: AuthorizationService? = null
    private val login = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        signingIn = false
        loginState = null
        authorizationService?.dispose(); authorizationService = null
        val response = result.data?.let(AuthorizationResponse::fromIntent)
        if (response == null) {
            loginError = "Sign-in did not complete. Try again, or use your browser app instead."
            if (!AppLock.locked(this)) render()
        } else lifecycleScope.launch {
            try { withContext(Dispatchers.IO) { account.complete(response) }; loginError = "" }
            catch (_: Exception) { loginError = "Saiph could not finish signing in. Check your connection and try again." }
            if (!AppLock.locked(this@HostedActivity)) render()
        }
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
        loginState = state?.getString("loginState")
        signingIn = state?.getBoolean("signingIn") == true && loginState != null &&
            loginState == prefs.getString("pending_state", null) &&
            prefs.getLong("pending_until", 0) > System.currentTimeMillis()
        if (!AppLock.locked(this)) render()
    }
    override fun onSaveInstanceState(state: Bundle) { state.putString("saving", saving); state.putBoolean("deploymentSettings", deploymentSettings); state.putBoolean("signingIn", signingIn); state.putString("loginState", loginState); super.onSaveInstanceState(state) }
    override fun onDestroy() { authorizationService?.dispose(); authorizationService = null; super.onDestroy() }
    override fun onResume() {
        super.onResume()
        if (runtime.enabled() && !sefirah.network.orion.OrionPause.paused(this)) ContextCompat.startForegroundService(this, Intent(this, HostedSyncService::class.java))
        lock.open(::lockedScreen, ::resumeUnlocked)
    }
    private fun resumeUnlocked() {
        if (showingLock || !::status.isInitialized) { showingLock = false; render() }
        UsageAnalytics.opened(this, "hosted")
        if (prefs.contains("device_id")) UsageAnalytics.ask(this) { render() }
        poll?.cancel()
        // The waiting screen turns into the daily screen by itself once the computer approves.
        poll = lifecycleScope.launch { while (isActive) { if (waitingForApproval() != shownWaiting) render() else status.text = statusLine(); delay(1000) } }
    }
    private fun lockedScreen() {
        if (showingLock) return
        showingLock = true; poll?.cancel()
        shell("Saiph is locked")
        root.addView(card().apply {
            addView(text("Confirm it's you to see Saiph Hosted.", 15f))
            actions(button("Unlock", true) { lock.declined = false; lock.open({}, ::resumeUnlocked) })
        })
    }
    override fun onPause() { poll?.cancel(); super.onPause() }
    override fun onStop() { lock.stopped(); super.onStop() }
    /** Actions that let another device in need the owner, not just an unlocked phone. */
    private fun verified(reason: String, requireScreenLock: Boolean = true, run: () -> Unit) =
        lock.confirm(reason, requireScreenLock, failure = ::message, success = run)
    private fun message(value: String) = Toast.makeText(this, value, Toast.LENGTH_LONG).show()
    /** AppAuth owns the browser round trip and verifies state and PKCE for either browser mode. */
    private fun signIn(browserApp: Boolean = false) {
        if (signingIn) return
        signingIn = true; loginState = null; loginError = ""; render()
        lifecycleScope.launch {
            try {
                withContext(Dispatchers.IO) {
                    if (!runtime.enabled()) { runtime.applyPackagedDefaults(); runtime.setEnabled(true) }
                }
                authorizationService?.dispose()
                val configuration = if (browserApp) AppAuthConfiguration.Builder()
                    .setBrowserMatcher { browser -> !browser.useCustomTab }.build() else AppAuthConfiguration.DEFAULT
                val service = AuthorizationService(this@HostedActivity, configuration)
                authorizationService = service
                val request = account.request()
                loginState = request.state
                login.launch(service.getAuthorizationRequestIntent(request))
            } catch (failure: CancellationException) {
                throw failure
            } catch (_: ActivityNotFoundException) {
                signingIn = false; loginState = null
                authorizationService?.dispose(); authorizationService = null
                loginError = "No browser is available for sign-in. Enable a browser in Android Settings, then try again."
                render()
            } catch (_: Exception) {
                signingIn = false; loginState = null
                authorizationService?.dispose(); authorizationService = null
                loginError = "Saiph could not open sign-in. Check your connection or download the current beta from your account page."
                render()
            }
        }
    }
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
    /** The same frame as the home screen: strings behind, a header with Back, then the page. */
    private fun shell(title: String) {
        root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dp(18), dp(4), dp(18), dp(28)) }
        val header = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL; gravity = android.view.Gravity.CENTER_VERTICAL
            setPadding(dp(10), dp(8), dp(10), dp(8)); minimumHeight = dp(64)
            addView(iconButton(com.castle.sefirah.R.drawable.saiph_ic_back, "Back") { finish() })
            addView(text(title, 22f, Palette.TEXT, true).apply { letterSpacing = -0.02f; androidx.core.view.ViewCompat.setAccessibilityHeading(this, true); setPadding(dp(2), 0, dp(8), 0) },
                LinearLayout.LayoutParams(0, android.view.ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        }
        val column = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            addView(header)
            addView(ScrollView(context).apply { addView(root) }, LinearLayout.LayoutParams(android.view.ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
        }
        val frame = FrameLayout(this).apply { addView(StringField(context)); addView(column) }
        frame.setOnApplyWindowInsetsListener { view, insets ->
            if (android.os.Build.VERSION.SDK_INT >= 30) {
                val bars = insets.getInsets(android.view.WindowInsets.Type.systemBars()); view.setPadding(0, bars.top, 0, bars.bottom)
            } else {
                @Suppress("DEPRECATION")
                view.setPadding(0, insets.systemWindowInsetTop, 0, insets.systemWindowInsetBottom)
            }
            insets
        }
        setContentView(frame)
    }
    /** A titled group of related controls on one surface. */
    private fun group(title: String, build: LinearLayout.() -> Unit) {
        root.addView(section(title)); root.addView(card().apply(build))
    }
    private fun LinearLayout.actions(vararg buttons: Button) = addView(buttonRow(*buttons))
    private fun granted(permission: String) = checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED
    /** Off by default: approved computers may act on texts and calls only after the owner turns this on here. */
    /** Off by default: approved computers may act on texts and calls only after the owner turns this on here. */
    private fun textsAndCalls() = group("Texts and calls") {
        addView(text("Show your texts and calls on your computers. From any computer approved for your Saiph account you can reply in " +
            "one-to-one conversations, start a new text, answer or decline a ringing call and dial a number, only while this is on. " +
            "If two computers answer or decline the same call, the first one wins and the other is told. " +
            "Texts, numbers and names are end-to-end encrypted; Saiph Hosted cannot read them. Pictures (MMS), group replies and call audio stay on this phone.", 14f, Palette.MUTED))
        if (runtime.textsAndCalls()) {
            addView(badge("On", Palette.GOOD, Palette.GOOD_SURFACE).apply { layoutParams = LinearLayout.LayoutParams(android.view.ViewGroup.LayoutParams.WRAP_CONTENT, android.view.ViewGroup.LayoutParams.WRAP_CONTENT).apply { topMargin = dp(10) } })
            val missing = PHONE_PERMISSIONS.filterNot(::granted)
            if (missing.isEmpty()) addView(text("Android access for messages, calls and contacts is allowed.", 13f, Palette.MUTED).apply { setPadding(0, dp(8), 0, 0) })
            else {
                addView(text("Some Android access is missing, so your computer shows less. Allow it, or manage it in Android Settings.", 13f, Palette.MUTED).apply { setPadding(0, dp(8), 0, 0) })
                actions(button("Allow messages and calls access", tone = Tone.TONAL) { requestPermissions(missing.toTypedArray(), 47) })
            }
            actions(button("Turn off texts and calls") { runtime.setTextsAndCalls(false); render() })
        } else actions(button("Turn on texts and calls", tone = Tone.TONAL) {
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
    private fun field(label: String, value: String = "", into: LinearLayout = root): EditText {
        into.addView(text(label, 13f, Palette.MUTED).apply { setPadding(dp(2), dp(8), 0, dp(6)) })
        // The shared field look from Ui.kt; a Context receiver reaches it rather than this method.
        return (this as android.content.Context).field(label).apply { setText(value); hint = null; contentDescription = label; into.addView(this) }
    }
    private fun render() {
        shell("Saiph Hosted")
        status = text(statusLine(), 13f, Palette.MUTED).apply { setPadding(dp(4), 0, 0, dp(6)) }; root.addView(status)
        if (getSharedPreferences("orion", 0).contains("device_id")) {
            root.addView(card().apply { addView(text("This phone is paired with a self-hosted Hub. Use an unpaired phone for Hosted.", 15f)) }); return
        }
        val enrolled = prefs.contains("device_id")
        // An approved phone keeps syncing with its device keys; the account token only matters
        // for enrolment, so only a phone that is not yet approved starts at sign-in.
        shownWaiting = waitingForApproval()
        if (!enrolled && !account.signedIn()) {
            signInScreen(enrolled)
            return
        }
        if (shownWaiting) {
            waitingScreen()
            return
        }
        if (!runtime.enabled()) {
            root.addView(card(strong = true).apply {
                addView(text("Sync is turned off on this phone. Your account and device approval are kept.", 15f))
                actions(button("Resume syncing", true) { toggleHosted() })
            })
            if (enrolled) retirementAction()
        } else if (enrolled) {
            // Daily use first: files across, then texts and calls.
            group("Send and receive") {
                addView(text("Send a file or photo to your computers, or save one they sent.", 14f, Palette.MUTED))
                actions(button("Choose a file or photo to send", true) { sendFile.launch(arrayOf("*/*")) })
                runtime.offers.forEach { (id, name) -> actions(button("Save $name", tone = Tone.TONAL) { saving = id; saveFile.launch(name) }) }
                actions(button("Refresh received files", tone = Tone.TONAL) { render() })
            }
            textsAndCalls()
            group("This phone") {
                addView(text("Your phone's full device fingerprint:\n${runtime.fingerprint}", 13f, Palette.MUTED))
                actions(button("Show a fresh device request", tone = Tone.TONAL) { verified("Show a request to add this phone") { action { runtime.freshRequest() } } })
                if (runtime.requestCode.isNotEmpty()) {
                    addView(text("Paste this request into the computer, compare this phone's full fingerprint, then approve.", 13f, Palette.MUTED).apply { setPadding(0, dp(10), 0, dp(6)) })
                    addView(context.field("Phone device approval request code").apply { setText(runtime.requestCode); isFocusable = false; contentDescription = "Phone device approval request code" })
                }
            }
        } else {
            group("Connect to your computer") {
                addView(text("On your computer, open Saiph and choose Show root approval code (in the setup guide, or Settings → Saiph account). Scan the code it shows.", 14f, Palette.MUTED))
                actions(button("Scan the code on your computer", true) { scanRoot.launch(OrionQrActivity.hostedRoot(this@HostedActivity)) })
                val code = field("Or paste the root approval code from your computer", into = this)
                actions(button("Check root code", tone = Tone.TONAL) { checkRoot(code.text.toString()) })
            }
        }
        if (runtime.enabled()) {
            group("Account") {
                if (account.signedIn()) actions(button("Sign out") { action { account.signOut() } })
                else {
                    addView(text("Sync keeps running. Sign in again only to change this phone's approval.", 14f, Palette.MUTED))
                    actions(button(if (signingIn) "Waiting for sign-in…" else "Sign in to Saiph") { signIn() }.apply { isEnabled = !signingIn })
                    if (loginError.isNotEmpty()) {
                        addView(text(loginError, 14f, Palette.WARN))
                        actions(button("Use browser app instead", tone = Tone.TONAL) { signIn(browserApp = true) }.apply { isEnabled = !signingIn })
                    }
                }
            }
            if (enrolled) group("Sharing permissions") {
                addView(text("Choose only the features you want. Notification access lets Saiph share your phone notifications. Android may restrict clipboard access while Saiph is in the background.", 14f, Palette.MUTED))
                fun settings(label: String, target: Intent) = actions(button(label, tone = Tone.TONAL) {
                    runCatching { startActivity(target) }.onFailure { message("Open Android Settings to manage Saiph permissions.") }
                })
                settings("Choose phone notification access", Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
                settings("Saiph connection notifications", Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, packageName))
                settings("Battery and background settings", Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName")))
            }
            group("Connection") {
                addView(text("Saiph Hosted is on. Turning it off stops sync on this phone.", 14f, Palette.MUTED))
                actions(button("Turn off Hosted") { toggleHosted() })
            }
        }
        root.addView(section("Security"))
        root.addView(card().apply {
            addView(lock.toggle())
            runtime.securityEvents().forEach { addView(text(it, 13f, Palette.MUTED)) }
        })
        UsageAnalytics.settingsViews(this).forEach(root::addView)
    }
    private fun signInScreen(enrolled: Boolean) {
        root.addView(card(strong = true).apply {
            addView(text("Your phone and computers, in tune.", 22f, bold = true))
            addView(text("Sign in with the same Saiph account you use on your computer. Connection settings are taken care of for you.", 15f))
            if (!signingIn && !enrolled) addView(text("New to the beta? Activate your invitation code on your Saiph account page first, with the account you sign in with here.", 13f, Palette.MUTED).apply { setPadding(0, dp(6), 0, 0) })
            actions(button(if (signingIn) "Waiting for sign-in…" else "Sign in to Saiph", true) { signIn() }.apply { isEnabled = !signingIn })
            if (signingIn) addView(text("Finish signing in in your browser, then return to Saiph.", 14f, Palette.MUTED))
            if (loginError.isNotEmpty()) {
                addView(text(loginError, 14f, Palette.WARN).apply { accessibilityLiveRegion = android.view.View.ACCESSIBILITY_LIVE_REGION_POLITE })
                actions(button("Use browser app instead", tone = Tone.TONAL) { signIn(browserApp = true) }.apply { isEnabled = !signingIn })
            }
        })
        if (!runtime.enabled() && !enrolled) {
            actionsOnRoot(button("I self-host my own Hub") {
                getSharedPreferences("orion", 0).edit().putBoolean("self_host", true).apply()
                finish()
            })
            // Custom builds retain manual configuration outside the normal account flow.
            if (!runtime.hasPackagedDefaults()) {
                actionsOnRoot(button(if (deploymentSettings) "Hide custom service settings" else "Custom service (advanced)", tone = Tone.TONAL) { deploymentSettings = !deploymentSettings; render() })
                if (deploymentSettings) group("Custom service") {
                    val origin = field("Hosted service address", prefs.getString("origin", "")!!, this)
                    val issuer = field("Sign-in issuer (HTTPS, ending in /)", prefs.getString("issuer", "")!!, this)
                    val audience = field("API audience", prefs.getString("audience", "")!!, this)
                    val client = field("Android native client ID", prefs.getString("client_id", "")!!, this)
                    val refresh = CheckBox(context).apply { text = "Keep me signed in with a protected rotating refresh token"; isChecked = prefs.getBoolean("refresh_tokens", false); setTextColor(Palette.TEXT); buttonTintList = android.content.res.ColorStateList.valueOf(Palette.ACCENT) }; addView(refresh)
                    actions(button("Save custom service") { verified("Change the Saiph Hosted connection", requireScreenLock = false) {
                        action { runtime.configure(origin.text.toString(), issuer.text.toString(), audience.text.toString(), client.text.toString(), refresh.isChecked) }
                    } })
                }
            }
        }
        if (!runtime.enabled() && enrolled) retirementAction()
    }
    private fun statusLine() = when {
        account.signedIn() -> runtime.status + " · Signed in"
        prefs.contains("device_id") -> runtime.status
        else -> ""
    }
    private fun waitingForApproval() = prefs.contains("device_id") && runtime.enabled() && runtime.status.startsWith("Waiting for root approval")
    /** One job while the computer has not approved this phone yet: compare and approve there. */
    private fun waitingScreen() {
        root.addView(card(strong = true).apply {
            addView(text("Approve this phone on your computer", 20f, bold = true))
            addView(text("Open Saiph on your computer. This phone appears there by itself. Check that every group of this fingerprint matches, then approve it:", 15f))
            if (runtime.fingerprint.isNotEmpty()) addView(text(runtime.fingerprint, 18f, bold = true).apply { setPadding(0, dp(10), 0, dp(10)); setTextIsSelectable(true) })
            addView(text("This screen moves on by itself once your computer approves the phone.", 14f, Palette.MUTED))
            actions(button("Send a fresh request", tone = Tone.TONAL) {
                if (!account.signedIn()) signIn() else verified("Show a request to add this phone") { action { runtime.freshRequest() } }
            })
            if (runtime.requestCode.isNotEmpty()) actions(button("Share the request code instead", tone = Tone.TONAL) {
                // Only public keys and a signature: safe to send to yourself if the computer cannot see the request.
                runCatching { startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, runtime.requestCode), "Share request code")) }
            })
            if (loginError.isNotEmpty()) addView(text(loginError, 14f, Palette.WARN))
        })
        retirementAction()
    }
    private fun actionsOnRoot(vararg buttons: Button) = root.addView(buttonRow(*buttons))
    private fun retirementAction() = actionsOnRoot(button("Retire this phone's Hosted identity", tone = Tone.DANGER) {
        android.app.AlertDialog.Builder(this).setTitle("Retire Hosted identity?").setMessage("Revoke this phone on the root computer too. Its encrypted keys and trust history stay on this phone for recovery.")
            .setNegativeButton("Cancel", null).setPositiveButton("Retire") { _, _ -> verified("Retire this phone's Hosted identity", requireScreenLock = false) { action { runtime.retire() } } }.show()
    })
    /** One switch for the whole service; starting it also applies this build's connection defaults. */
    private fun toggleHosted() = action {
        val enabled = !runtime.enabled()
        if (enabled) runtime.applyPackagedDefaults()
        runtime.setEnabled(enabled)
        if (enabled) ContextCompat.startForegroundService(this@HostedActivity, Intent(this@HostedActivity, HostedSyncService::class.java)) else stopService(Intent(this@HostedActivity, HostedSyncService::class.java))
    }
}
