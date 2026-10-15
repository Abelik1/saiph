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
import androidx.activity.OnBackPressedCallback
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
    private lateinit var scroll: ScrollView
    private var shownPage = ""
    private var saving = ""
    private var poll: Job? = null
    private var deploymentSettings = false
    private var settingsPage = false
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
        settingsPage = state?.getBoolean("settingsPage") ?: false
        loginState = state?.getString("loginState")
        signingIn = state?.getBoolean("signingIn") == true && loginState != null &&
            loginState == prefs.getString("pending_state", null) &&
            prefs.getLong("pending_until", 0) > System.currentTimeMillis()
        if (!AppLock.locked(this)) render()
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (settingsPage && !showingLock) { settingsPage = false; render() }
                else { isEnabled = false; onBackPressedDispatcher.onBackPressed(); isEnabled = true }
            }
        })
    }
    override fun onSaveInstanceState(state: Bundle) { state.putBoolean("settingsPage", settingsPage); state.putString("saving", saving); state.putBoolean("deploymentSettings", deploymentSettings); state.putBoolean("signingIn", signingIn); state.putString("loginState", loginState); super.onSaveInstanceState(state) }
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
            addView(text("Confirm it's you to see Saiph Hosted.", UiType.BODY))
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
            android.app.AlertDialog.Builder(this).setTitle("Check this computer's security code").setMessage("Compare every group below with the code shown on your computer. This checks which computer you are trusting:\n\n$fingerprint")
                .setNegativeButton("Cancel", null).setPositiveButton("Every group matches") { _, _ ->
                    verified("Trust your computer as this phone's root device") { action { runtime.enroll(value, fingerprint) } }
                }.show()
        }.onFailure { message("Invalid or expired root code. Ask your computer for a new code.") }
    }
    /** The same frame as the home screen: strings behind, a header with Back, then the page. */
    private fun shell(title: String, page: String = title) {
        val restoreScroll = if (::scroll.isInitialized && shownPage == page) scroll.scrollY else 0
        shownPage = page
        root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dp(18), dp(4), dp(18), dp(28)) }
        val header = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL; gravity = android.view.Gravity.CENTER_VERTICAL
            setPadding(dp(10), dp(8), dp(10), dp(8)); minimumHeight = dp(64)
            addView(iconButton(com.castle.sefirah.R.drawable.saiph_ic_back, "Back") {
                if (settingsPage && !showingLock) { settingsPage = false; render() } else finish()
            })
            addView(heading(title).apply { setPadding(dp(2), 0, dp(8), 0) },
                LinearLayout.LayoutParams(0, android.view.ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
            if (!showingLock && !settingsPage && prefs.contains("device_id") && !waitingForApproval()) {
                addView(iconButton(com.castle.sefirah.R.drawable.saiph_ic_settings, "Settings") { settingsPage = true; render() })
            }
        }
        scroll = ScrollView(this).apply { addView(root) }
        val column = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            addView(header)
            addView(scroll, LinearLayout.LayoutParams(android.view.ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
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
        val pageScroll = scroll
        pageScroll.post { pageScroll.scrollTo(0, restoreScroll) }
    }
    /** A titled group of related controls on one surface. */
    private fun group(title: String, build: LinearLayout.() -> Unit) {
        root.addView(section(title)); root.addView(card().apply(build))
    }
    private fun LinearLayout.actions(vararg buttons: Button) = addView(buttonRow(*buttons))
    private fun granted(permission: String) = checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED
    /** Off by default: approved computers may act on texts and calls only after the owner turns this on here. */
    private fun textsAndCalls() = group("Texts and calls") {
        addView(featureRow(sefirah.common.R.drawable.ic_chat, "Texts", "Read and reply to one-to-one texts, or start a conversation."))
        addView(featureRow(sefirah.common.R.drawable.ic_call, "Calls", "Answer, decline or dial from your computer. Audio stays on your phone."))
        addView(divider())
        addView(body("When enabled, every approved computer on your account can use these features."))
        if (runtime.textsAndCalls()) {
            addView(badge("On", Palette.GOOD, Palette.GOOD_SURFACE).apply { layoutParams = LinearLayout.LayoutParams(android.view.ViewGroup.LayoutParams.WRAP_CONTENT, android.view.ViewGroup.LayoutParams.WRAP_CONTENT).apply { topMargin = dp(10) } })
            val missing = PHONE_PERMISSIONS.filterNot(::granted)
            if (missing.isEmpty()) addView(body("Android access is allowed.").apply { setPadding(0, dp(8), 0, 0) })
            else {
                addView(body("Some Android access is missing. Allow it to use all text and call features.").apply { setPadding(0, dp(8), 0, 0) })
                actions(button("Allow Android access", tone = Tone.TONAL) { requestPermissions(missing.toTypedArray(), 47) })
            }
            actions(button("Turn off texts and calls") { runtime.setTextsAndCalls(false); render() })
        } else actions(button("Turn on texts and calls", tone = Tone.TONAL) {
            verified("Let your computer send texts and handle calls") {
                runtime.setTextsAndCalls(true)
                PHONE_PERMISSIONS.filterNot(::granted).takeIf { it.isNotEmpty() }?.let { requestPermissions(it.toTypedArray(), 47) }
                render()
            }
        })
        addView(disclosure("Privacy and limits") {
            addView(body("Texts, numbers and names are end-to-end encrypted; Saiph Hosted cannot read them."))
            addView(body("Pictures (MMS) and group replies stay on this phone.").apply { setPadding(0, dp(12), 0, 0) })
            addView(body("If two computers answer or decline the same call, the first action wins. The other computer is told.").apply { setPadding(0, dp(12), 0, 0) })
        })
    }
    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == 47 && !showingLock) render()
    }
    private fun field(label: String, value: String = "", into: LinearLayout = root): EditText {
        val labelView = text(label, UiType.BODY, Palette.MUTED).apply { setPadding(dp(2), dp(8), 0, dp(6)) }
        into.addView(labelView)
        // The shared field look from Ui.kt; a Context receiver reaches it rather than this method.
        return (this as android.content.Context).field(label).apply {
            id = android.view.View.generateViewId(); labelView.labelFor = id
            setText(value); hint = null; contentDescription = label; into.addView(this)
        }
    }
    private fun render() {
        if (!prefs.contains("device_id") || waitingForApproval()) settingsPage = false
        val enrolled = prefs.contains("device_id")
        val page = when {
            settingsPage -> "settings"
            !enrolled && !account.signedIn() -> "sign-in"
            waitingForApproval() -> "waiting"
            !runtime.enabled() -> "paused"
            enrolled -> "home"
            else -> "connect"
        }
        shell(if (settingsPage) "Settings" else "Saiph", page)
        status = text(statusLine(), UiType.META, Palette.MUTED).apply { setPadding(dp(2), 0, 0, dp(6)); visibility = if (text.isEmpty()) android.view.View.GONE else android.view.View.VISIBLE }; root.addView(status)
        if (getSharedPreferences("orion", 0).contains("device_id")) {
            root.addView(card().apply { addView(text("This phone is paired with a self-hosted Hub. Use an unpaired phone for Hosted.", UiType.BODY)) }); return
        }
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
        if (settingsPage) { hostedSettings(); return }
        if (!runtime.enabled()) {
            root.addView(card(strong = true).apply {
                addView(text("Sync is turned off on this phone. Your account and device approval are kept.", UiType.BODY))
                actions(button("Resume syncing", true) { toggleHosted() })
            })
            if (enrolled) retirementAction()
        } else if (enrolled) {
            // Daily use first: files across, then texts and calls.
            group("Files and photos") {
                addView(featureRow(com.castle.sefirah.R.drawable.saiph_ic_photo, "Send to your computers", "Choose a file or photo from this phone."))
                actions(button("Send a file or photo", true) { sendFile.launch(arrayOf("*/*")) })
                addView(divider())
                addView(cardTitle("Received files"))
                if (runtime.offers.isEmpty()) addView(body("Files sent from your computers appear here."))
                runtime.offers.forEachIndexed { index, (id, name) ->
                    if (index > 0) addView(divider())
                    addView(text(name))
                    actions(button("Save file", tone = Tone.TONAL) { saving = id; saveFile.launch(name) }.apply { contentDescription = "Save $name" })
                }
                actions(button("Refresh files") { render() })
            }
            textsAndCalls()
        } else {
            group("Connect to your computer") {
                addView(body("Open the Phone tab in Saiph on your computer. Its connection screen shows the QR code; to add another phone, choose Connect a phone."))
                actions(button("Scan the code on your computer", true) { scanRoot.launch(OrionQrActivity.hostedRoot(this@HostedActivity)) })
                addView(disclosure("Paste a code instead") {
                    val code = field("Computer code", into = this)
                    actions(button("Check code", tone = Tone.TONAL) { checkRoot(code.text.toString()) })
                })
            }
        }
    }
    private fun hostedSettings() {
        val enrolled = prefs.contains("device_id")
        group("This phone") {
            addView(body("Full device fingerprint"))
            addView(text(runtime.fingerprint, UiType.META).apply { setPadding(0, dp(8), 0, 0); setTextIsSelectable(true) })
            actions(button("Create a fresh request", tone = Tone.TONAL) { verified("Show a request to add this phone") { action { runtime.freshRequest() } } })
            if (runtime.requestCode.isNotEmpty()) addView(disclosure("View approval request code") {
                addView(body("Paste this request into your computer. Compare every fingerprint group before approving.").apply { setPadding(0, dp(12), 0, dp(8)) })
                addView(context.field("Phone device approval request code").apply { setText(runtime.requestCode); isFocusable = false; contentDescription = "Phone device approval request code" })
            })
        }
        if (runtime.enabled()) {
            group("Account") {
                if (account.signedIn()) actions(button("Sign out") { action { account.signOut() } })
                else {
                    addView(text("Sync keeps running. Sign in again only to change this phone's approval.", UiType.BODY, Palette.MUTED))
                    actions(button(if (signingIn) "Waiting for sign-in…" else "Sign in to Saiph") { signIn() }.apply { isEnabled = !signingIn })
                    if (loginError.isNotEmpty()) {
                        addView(text(loginError, UiType.BODY, Palette.WARN))
                        actions(button("Use browser app instead", tone = Tone.TONAL) { signIn(browserApp = true) }.apply { isEnabled = !signingIn })
                    }
                }
            }
            if (enrolled) group("Sharing permissions") {
                fun settings(label: String, target: Intent) = actions(button(label, tone = Tone.TONAL) {
                    runCatching { startActivity(target) }.onFailure { message("Open Android Settings to manage Saiph permissions.") }
                })
                addView(cardTitle("Phone notifications"))
                addView(body("Allow Saiph to share notifications with your computers."))
                settings("Manage notification access", Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
                addView(divider())
                addView(cardTitle("Connection notifications"))
                addView(body("Choose which Saiph status alerts appear on this phone."))
                settings("Manage Saiph notifications", Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, packageName))
                addView(divider())
                addView(cardTitle("Background activity"))
                addView(body("Manage battery restrictions. Android may limit clipboard access in the background."))
                settings("Open app settings", Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName")))
            }
            group("Connection") {
                addView(body("Turning sync off keeps your account and device approval."))
                actions(button("Turn off sync") { toggleHosted() })
            }
        } else group("Connection") {
            addView(body("Sync is off. Your account and device approval are kept."))
            actions(button("Resume syncing", true) { toggleHosted() })
        }
        root.addView(section("Security"))
        root.addView(card().apply {
            addView(lock.toggle())
            runtime.securityEvents().forEach { addView(text(it, UiType.META, Palette.MUTED)) }
        })
        UsageAnalytics.settingsViews(this).forEach(root::addView)
    }
    private fun signInScreen(enrolled: Boolean) {
        root.addView(heading("Your devices, in tune.").apply { setPadding(dp(2), dp(16), 0, dp(8)) })
        root.addView(body("Choose how to connect your phone.").apply { setPadding(dp(2), 0, 0, dp(24)) })
        root.addView(card().apply {
            addView(cardTitle("Use your Saiph account"))
            addView(body("Sign in with the same account as your computer. Saiph takes care of the connection."))
            actions(button(if (signingIn) "Waiting for sign-in…" else "Sign in to Saiph", true) { signIn() }.apply { isEnabled = !signingIn })
            if (signingIn) addView(body("Finish signing in in your browser, then return here.").apply { setPadding(0, dp(12), 0, 0) })
            if (loginError.isNotEmpty()) {
                addView(text(loginError, UiType.BODY, Palette.WARN).apply { accessibilityLiveRegion = android.view.View.ACCESSIBILITY_LIVE_REGION_POLITE })
                actions(button("Use browser app instead", tone = Tone.TONAL) { signIn(browserApp = true) }.apply { isEnabled = !signingIn })
            }
        })
        if (!runtime.enabled() && !enrolled) {
            root.addView(connectionChoice("Use your own Hub", "Connect through a Saiph Hub you manage on your own network.", "Connect to my Hub") {
                getSharedPreferences("orion", 0).edit().putBoolean("self_host", true).apply()
                finish()
            })
        }
        if (!signingIn && !enrolled) root.addView(disclosure("New to the beta?") {
            addView(body("Activate your invitation code on your Saiph account page first. Use that same account to sign in here."))
        })
        if (!runtime.enabled() && !enrolled) {
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
            addView(cardTitle("Approve this phone"))
            addView(body("Open the Phone tab in Saiph on your computer. Compare every group of this security code with the phone request shown there, then approve it."))
            if (runtime.fingerprint.isNotEmpty()) addView(text(runtime.fingerprint, 18f, bold = true).apply { setPadding(0, dp(10), 0, dp(10)); setTextIsSelectable(true) })
            addView(text("This screen moves on by itself once your computer approves the phone.", UiType.BODY, Palette.MUTED))
            actions(button("Send a fresh request", tone = Tone.TONAL) {
                if (!account.signedIn()) signIn() else verified("Show a request to add this phone") { action { runtime.freshRequest() } }
            })
            if (runtime.requestCode.isNotEmpty()) actions(button("Share the request code instead", tone = Tone.TONAL) {
                // Only public keys and a signature: safe to send to yourself if the computer cannot see the request.
                runCatching { startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, runtime.requestCode), "Share request code")) }
            })
            if (loginError.isNotEmpty()) addView(text(loginError, UiType.BODY, Palette.WARN))
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
