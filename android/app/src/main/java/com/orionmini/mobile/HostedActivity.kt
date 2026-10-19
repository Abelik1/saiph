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
import kotlinx.coroutines.sync.withLock
import net.openid.appauth.AuthorizationResponse
import net.openid.appauth.AuthorizationService
import net.openid.appauth.AppAuthConfiguration
import sefirah.network.orion.HostedApprovalCodes

private val PHONE_PERMISSIONS = listOf(Manifest.permission.READ_SMS, Manifest.permission.SEND_SMS, Manifest.permission.RECEIVE_SMS,
    Manifest.permission.READ_PHONE_STATE, Manifest.permission.ANSWER_PHONE_CALLS, Manifest.permission.CALL_PHONE,
    Manifest.permission.READ_CALL_LOG, Manifest.permission.READ_CONTACTS)

/** A computer code the owner is comparing: the signed code and its displayed fingerprint. */
private data class PendingRoot(val code: String, val fingerprint: String)

/** Account sign-in first; choosing Sign in applies this build's public defaults. */
class HostedActivity : ComponentActivity() {
    companion object { const val SHOW_WELCOME = "show_account_welcome" }
    private val lock = AppLock(this)
    private var showingLock = false
    private val runtime by lazy { HostedRuntime.get(this) }
    private val account by lazy { HostedAccount.get(this) }
    private val prefs by lazy { getSharedPreferences("orion_hosted", 0) }
    private lateinit var root: LinearLayout
    private lateinit var status: TextView
    private lateinit var scroll: ScrollView
    private lateinit var setupDock: LinearLayout
    private var shownPage = ""
    private var saving = ""
    private var poll: Job? = null
    private var settingsPage = false
    /** The open Settings category page; null shows the category list and search. */
    private var settingsCategory: SettingsCatalog.Category? = null
    private var settingsQuery = ""
    /** A searched item to scroll to once its category page is drawn. */
    private var settingsTarget = ""
    private var welcomePage = false
    private var signingIn = false
    private var googleSignIn = true
    private var shownWaiting = false
    private var shownStage = HostedSetup.Stage.SCAN
    private var busy = false
    private var actionError = ""
    /** Received-file ids the daily screen last drew; a change redraws it without a Refresh button. */
    private var shownOffers: List<String> = emptyList()
    /** Progress lines of files arriving over the local network, refreshed by the poll loop. */
    private val lanLines = mutableMapOf<String, android.widget.TextView>()
    /** A scanned or pasted computer code waiting for the owner's group-by-group comparison. */
    private var pendingRoot: PendingRoot? = null
    /** A computer found on this Wi-Fi, comparing a six-digit code; its connection stays open until confirmed or cancelled. */
    private var nearby: LanLink.Session? = null
    private var nearbyRoot: PendingRoot? = null
    private var nearbyCode = ""
    private var nearbyChoices: List<LanLink.Computer>? = null
    private var searching = false
    /** After confirming: the compared code, and whether the computer received the request over Wi-Fi. */
    private var nearbyCompared = ""
    private var nearbyDelivered = false
    private var loginState: String? = null
    private var loginError = ""
    private var authorizationService: AuthorizationService? = null
    private var permissionRequest = ""
    private var returningFromSettings = false
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
            catch (failure: CancellationException) { throw failure }
            catch (failure: Exception) {
                val issue = HostedSignIn.issue(failure)
                // A fixed category is sufficient for attended diagnostics. Never
                // log an exception body, callback, authorization code or token.
                android.util.Log.w("SaiphSignIn", "failure=" + issue.code)
                loginError = issue.message
            }
            if (!AppLock.locked(this@HostedActivity)) render()
        }
    }
    private val scanRoot = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        result.data?.getStringExtra(OrionQrActivity.HOSTED_ROOT_CODE)?.let(::checkRoot)
    }
    private val sendFile =registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) action {
            val name = runtime.sendFile(uri)
            withContext(Dispatchers.Main) { message(HostedTransferText.sent(listOf(name), "your main computer")) }
        }
    }
    private val saveFile = registerForActivityResult(ActivityResultContracts.CreateDocument("application/octet-stream")) { uri ->
        if (uri != null && saving.isNotEmpty()) { val id = saving; saving = ""; action { runtime.saveFile(id, uri) } }
    }
    // Append launchers after the existing ones: Android persists their generated keys
    // across activity recreation and an APK update during browser sign-in.
    private val sharingPermissions = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) {
        val requested = permissionRequest
        permissionRequest = ""
        runtime.photosRevision++
        runtime.wake.trySend(Unit)
        if (showingLock || AppLock.locked(this)) return@registerForActivityResult
        render()
        val access = sefirah.network.orion.OrionPermissions.read(this)
        if ((requested == "photos" && !access.photos) || (requested == "phone" && PHONE_PERMISSIONS.any { !granted(it) })) {
            android.app.AlertDialog.Builder(this).setTitle("Finish in Android Settings")
                .setMessage(if (requested == "photos") "Photo access is still off. You can allow selected photos or your photo library in Saiph's permissions."
                    else "Some text or call permissions are still off. Open Saiph's permissions to allow them. Android may restrict these on sideloaded apps.")
                .setNegativeButton("Not now", null).setPositiveButton("Open permissions") { _, _ -> openAppPermissions() }.show()
        }
    }
    override fun onCreate(state: Bundle?) {
        super.onCreate(state); lock.protectWindow()
        runtime.applyPackagedDefaults()
        permissionRequest = state?.getString("permissionRequest") ?: ""
        returningFromSettings = state?.getBoolean("returningFromSettings") ?: false
        saving = state?.getString("saving") ?: ""
        settingsPage = state?.getBoolean("settingsPage") ?: false
        settingsCategory = state?.getString("settingsCategory")?.let { name -> SettingsCatalog.Category.entries.firstOrNull { it.name == name } }
        settingsQuery = state?.getString("settingsQuery") ?: ""
        welcomePage = state?.getBoolean("welcomePage") ?: intent.getBooleanExtra(SHOW_WELCOME, false)
        intent.removeExtra(SHOW_WELCOME)
        loginState = state?.getString("loginState")
        googleSignIn = state?.getBoolean("googleSignIn") ?: true
        pendingRoot = state?.getString("pendingRootCode")?.let { code -> state.getString("pendingRootFingerprint")?.let { PendingRoot(code, it) } }
        signingIn = state?.getBoolean("signingIn") == true && loginState != null &&
            loginState == prefs.getString("pending_state", null) &&
            prefs.getLong("pending_until", 0) > System.currentTimeMillis()
        if (!AppLock.locked(this)) render()
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() = goBack()
        })
    }
    override fun onSaveInstanceState(state: Bundle) {
        state.putBoolean("settingsPage", settingsPage); state.putString("saving", saving)
        state.putString("settingsCategory", settingsCategory?.name); state.putString("settingsQuery", settingsQuery)
        state.putBoolean("welcomePage", welcomePage)
        state.putBoolean("signingIn", signingIn); state.putString("loginState", loginState)
        state.putBoolean("googleSignIn", googleSignIn)
        state.putString("permissionRequest", permissionRequest)
        state.putBoolean("returningFromSettings", returningFromSettings)
        // Only public keys and a signature: safe to keep across a rotation while the owner compares.
        pendingRoot?.let { state.putString("pendingRootCode", it.code); state.putString("pendingRootFingerprint", it.fingerprint) }
        super.onSaveInstanceState(state)
    }
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent); setIntent(intent)
        if (intent.getBooleanExtra(SHOW_WELCOME, false)) { welcomePage = true; pendingRoot = null }
        intent.removeExtra(SHOW_WELCOME)
        if (!AppLock.locked(this)) render()
    }
    override fun onDestroy() { cancelNearby(); authorizationService?.dispose(); authorizationService = null; super.onDestroy() }
    override fun onResume() {
        super.onResume()
        runtime.photosRevision++
        if (runtime.enabled() && !sefirah.network.orion.OrionPause.paused(this)) ContextCompat.startForegroundService(this, Intent(this, HostedSyncService::class.java))
        lock.open(::lockedScreen, ::resumeUnlocked)
    }
    private fun resumeUnlocked() {
        if (showingLock || !::status.isInitialized || returningFromSettings) { showingLock = false; returningFromSettings = false; render() }
        runtime.wake.trySend(Unit)
        UsageAnalytics.opened(this, "hosted")
        if (runtime.setupStage() == HostedSetup.Stage.HOME && account.signedIn() &&
            prefs.getBoolean("sharing_setup_complete", false) && permissionRequest.isEmpty()) UsageAnalytics.ask(this) { render() }
        poll?.cancel()
        // The waiting screen turns into the daily screen by itself once the computer approves.
        // Received files appear by themselves too; a changed list redraws the daily screen in place.
        poll = lifecycleScope.launch { while (isActive) {
            if (!busy && permissionRequest.isEmpty() && !lock.prompting && (runtime.setupStage() != shownStage || (shownPage == "home" && receivedKeys() != shownOffers))) render()
            else {
                status.text = statusLine()
                for (item in runtime.lanReceived()) lanLines[item.id]?.text = lanLine(item)
            }
            delay(1000)
        } }
    }
    private fun lockedScreen() {
        if (showingLock) return
        showingLock = true; poll?.cancel()
        shell("Saiph is locked")
        root.addView(card().apply {
            addView(text("Confirm it's you to open Saiph.", UiType.BODY))
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
    private fun signIn(browserApp: Boolean = false, google: Boolean = true) {
        if (signingIn || busy) return
        if (account.signedIn()) { welcomePage = false; render(); return }
        welcomePage = false; googleSignIn = google; signingIn = true; loginState = null; loginError = ""; render()
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
                val request = account.request(google)
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
        if (busy) return
        busy = true; actionError = ""; render()
        lifecycleScope.launch {
            try { withContext(Dispatchers.IO) { run() } }
            catch (failure: CancellationException) { throw failure }
            catch (refused: TransferRefused) { actionError = refused.message.orEmpty() }
            catch (_: Exception) {
                actionError = when {
                    runtime.setupStage() == HostedSetup.Stage.RECOVERY -> "This setup could not finish. Restart setup to scan your computer again."
                    !account.signedIn() -> "Sign in again to continue. Your device approval has been kept."
                    else -> "Could not reach Saiph. Check your connection and try again."
                }
            } finally {
                busy = false
                if (prefs.contains("device_id")) pendingRoot = null
                if (!isDestroyed && !AppLock.locked(this@HostedActivity)) render()
            }
        }
    }
    /** Scanned and pasted codes take the same path: nothing is trusted until every fingerprint group is confirmed. */
    private fun checkRoot(value: String) {
        if (busy || prefs.contains("device_id")) return
        runCatching {
            val inspected = HostedApprovalCodes.inspect(value)
            pendingRoot = PendingRoot(value, HostedApprovalCodes.displayFingerprint(inspected.fingerprint()))
            if (!AppLock.locked(this)) render()
        }.onFailure { message("Invalid or expired computer code. Ask your computer for a new code.") }
    }
    /** The trust step on its own themed screen: the full code, grouped, then one explicit confirmation. */
    private fun confirmRootScreen(pending: PendingRoot) {
        root.addView(setupProgress(1))
        root.addView(card(strong = true).apply {
            addView(cardTitle("Check this computer's security code"))
            addView(body("Compare every group below with the code shown on your computer. This checks which computer you are trusting."))
            addView(securityCode(pending.fingerprint))
            addView(disclosure("Why compare security codes?") {
                addView(body("A security code is the fingerprint of a device's encryption keys. Signing in finds your account; comparing every group on both screens checks which computer you are trusting."))
            })
            actions(button("Cancel") { pendingRoot = null; render() }, button("Every group matches", true) {
                verified("Trust this computer as your main computer") { action { runtime.enroll(pending.code, pending.fingerprint) } }
            })
        })
    }
    private fun phoneName(): String = runCatching { Settings.Global.getString(contentResolver, "device_name") }.getOrNull()
        ?.takeIf { it.isNotBlank() } ?: android.os.Build.MODEL ?: "Phone"
    /** Ask this Wi-Fi for a main computer whose Add a device window is open. */
    private fun findComputer() {
        if (busy || searching || prefs.contains("device_id")) return
        searching = true; actionError = ""; render()
        lifecycleScope.launch {
            val found = withContext(Dispatchers.IO) { runCatching { LanLink.discover() }.getOrDefault(emptyList()) }
            searching = false
            when (found.size) {
                0 -> { actionError = "No computer found on this Wi-Fi. On your computer, open Saiph → Phone → Add a device and try again, or scan its QR code."
                    if (!AppLock.locked(this@HostedActivity)) render() }
                1 -> connectNearby(found[0])
                else -> { nearbyChoices = found; if (!AppLock.locked(this@HostedActivity)) render() }
            }
        }
    }
    private fun chooseComputerScreen(computers: List<LanLink.Computer>) {
        root.addView(setupProgress(1))
        root.addView(card(strong = true).apply {
            addView(cardTitle("Choose your computer"))
            addView(body("More than one computer on this Wi-Fi is waiting for a phone."))
            computers.forEach { computer -> actions(button(computer.name, tone = Tone.TONAL) { connectNearby(computer) }) }
            actions(button("Cancel") { cancelNearby(); render() })
        })
    }
    private fun connectNearby(computer: LanLink.Computer) {
        nearbyChoices = null; searching = true; actionError = ""; render()
        lifecycleScope.launch {
            val result = withContext(Dispatchers.IO) { runCatching {
                val session = LanLink.Session(computer, phoneName())
                try {
                    session.compare()
                    // A signed, unexpired root code; trust is pinned only after the owner confirms the code.
                    session to HostedApprovalCodes.inspect(session.handshake.rootCode)
                } catch (failure: Exception) { session.close(); throw failure }
            } }
            searching = false
            result.onSuccess { (session, inspected) ->
                nearby?.close(); nearby = session; nearbyCode = session.handshake.code
                nearbyRoot = PendingRoot(session.handshake.rootCode, HostedApprovalCodes.displayFingerprint(inspected.fingerprint()))
            }.onFailure { actionError = "Could not connect to ${computer.name}. Keep Add a device open on your computer, or scan its QR code." }
            if (!AppLock.locked(this@HostedActivity)) render()
        }
    }
    private fun cancelNearby() {
        nearby?.close(); nearby = null; nearbyRoot = null; nearbyChoices = null; nearbyCode = ""
    }
    /** Both screens show the same six digits only if nothing sits between this phone and the computer. */
    private fun nearbyScreen() {
        root.addView(setupProgress(1))
        root.addView(card(strong = true).apply {
            addView(cardTitle("Check the code on your computer"))
            addView(body("Your computer shows a six-digit code. Continue only if it is exactly this one."))
            addView(text(nearbyCode, UiType.SCREEN, bold = true).apply {
                contentDescription = "Comparison code " + nearbyCode; setPadding(0, dp(12), 0, dp(12))
            })
            addView(disclosure("Why compare codes?") {
                addView(body("The code comes from both devices' keys for this connection. Matching codes show this phone reached your computer with nobody in between. Your computer still asks you to approve."))
            })
            actions(button("Codes differ") { cancelNearby(); message("Nothing was connected. Scan the QR code on your computer instead."); render() },
                button("Codes match", true) { confirmNearby() })
        })
    }
    private fun confirmNearby() {
        val session = nearby ?: return
        val pending = nearbyRoot ?: return
        val compared = nearbyCode
        verified("Trust this computer as your main computer") {
            action {
                runtime.enroll(pending.code, pending.fingerprint)
                nearbyCompared = compared
                // The request also reaches the computer through Saiph Cloud; Wi-Fi only skips the long comparison.
                nearbyDelivered = runCatching { session.sendRequest(runtime.requestCode) }.isSuccess
                session.close()
            }
        }
    }
    /** Only nested pages show an in-app Back arrow; Android owns leaving the activity. */
    private fun goBack() {
        if (busy) return
        when {
            showingLock -> finish()
            pendingRoot != null -> { pendingRoot = null; render() }
            nearbyRoot != null || nearbyChoices != null -> { cancelNearby(); render() }
            settingsPage && settingsCategory != null -> { settingsCategory = null; render() }
            settingsPage -> { settingsPage = false; settingsQuery = ""; render() }
            else -> finish()
        }
    }
    /** The same frame as the home screen: strings behind, a header with Back, then the page. */
    private fun shell(title: String, page: String = title) {
        val restoreScroll = if (::scroll.isInitialized && shownPage == page) scroll.scrollY else 0
        shownPage = page
        root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dp(18), dp(4), dp(18), dp(28)) }
        val header = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL; gravity = android.view.Gravity.CENTER_VERTICAL
            setPadding(dp(10), dp(8), dp(10), dp(8)); minimumHeight = dp(64)
            if (!showingLock && (settingsPage || pendingRoot != null)) addView(iconButton(com.castle.sefirah.R.drawable.saiph_ic_back, "Back", ::goBack))
            addView(heading(title).apply { setPadding(dp(2), 0, dp(8), 0) },
                LinearLayout.LayoutParams(0, android.view.ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
            if (!showingLock && !settingsPage && (prefs.contains("device_id") || account.signedIn())) {
                addView(iconButton(com.castle.sefirah.R.drawable.saiph_ic_settings, "Settings") { settingsPage = true; settingsCategory = null; render() })
            }
        }
        scroll = ScrollView(this).apply { addView(root) }
        setupDock = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; visibility = android.view.View.GONE
            background = outline(Palette.BG, Palette.LINE, 0); setPadding(dp(18), dp(4), dp(18), dp(12))
        }
        val column = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            addView(header)
            addView(scroll, LinearLayout.LayoutParams(android.view.ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
            addView(setupDock)
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
    private fun dockActions(vararg buttons: Button) {
        setupDock.visibility = android.view.View.VISIBLE
        setupDock.addView(buttonRow(*buttons))
    }
    private fun setupIntro(scene: SetupArtwork.Scene, title: String, detail: String) {
        val artwork = SetupArtwork(this, scene)
        // At large text sizes the task takes priority over decorative imagery.
        if (resources.configuration.fontScale <= 1.3f) root.addView(artwork)
        root.addView(heading(title))
        root.addView(body(detail).apply { setPadding(0, dp(8), 0, dp(12)) })
        if (resources.configuration.fontScale > 1.3f) root.addView(artwork)
    }
    private fun granted(permission: String) = checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED
    private fun photoPermissions() = if (android.os.Build.VERSION.SDK_INT >= 34)
        arrayOf(Manifest.permission.READ_MEDIA_IMAGES, Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED)
        else if (android.os.Build.VERSION.SDK_INT >= 33) arrayOf(Manifest.permission.READ_MEDIA_IMAGES)
        else arrayOf(Manifest.permission.READ_EXTERNAL_STORAGE)
    private fun allowPhotos() {
        verified("Share recent photos with your approved computers") {
            runtime.setPhotosShared(true)
            if (sefirah.network.orion.OrionPermissions.read(this).photos) render() else requestSharingPermissions("photos")
        }
    }
    private fun openAppPermissions() = openSharingSettings(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName")))
    private fun openSharingSettings(target: Intent) {
        returningFromSettings = true
        runCatching { startActivity(target) }.onFailure { returningFromSettings = false; message("Open Android Settings → Apps → Saiph → Permissions.") }
    }
    private fun requestSharingPermissions(feature: String) {
        if (permissionRequest.isNotEmpty()) return
        val permissions = if (feature == "photos") photoPermissions().toList() else PHONE_PERMISSIONS
        val missing = permissions.filterNot(::granted)
        val selected = feature == "photos" && android.os.Build.VERSION.SDK_INT >= 34 &&
            granted(Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED) && !granted(Manifest.permission.READ_MEDIA_IMAGES)
        val asked = prefs.getBoolean("permission_requested_$feature", false)
        if (HostedSharing.route(missing.isEmpty(), selected, asked, missing.any(::shouldShowRequestPermissionRationale)) == HostedSharing.Route.SETTINGS) {
            openAppPermissions(); return
        }
        check(prefs.edit().putBoolean("permission_requested_$feature", true).commit())
        permissionRequest = feature
        sharingPermissions.launch(permissions.toTypedArray())
    }
    private fun allowPhone() {
        if (runtime.textsAndCalls()) requestSharingPermissions("phone")
        else verified("Let your computer send texts and handle calls") {
            runtime.setTextsAndCalls(true)
            if (PHONE_PERMISSIONS.all(::granted)) render() else requestSharingPermissions("phone")
        }
    }
    private fun notificationAccess() {
        val component = android.content.ComponentName(this, sefirah.notification.NotificationListener::class.java)
        val target = if (android.os.Build.VERSION.SDK_INT >= 30)
            Intent(Settings.ACTION_NOTIFICATION_LISTENER_DETAIL_SETTINGS).putExtra(Settings.EXTRA_NOTIFICATION_LISTENER_COMPONENT_NAME, component.flattenToString())
            else Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS)
        if (target.resolveActivity(packageManager) != null) openSharingSettings(target)
        else openSharingSettings(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
    }
    /** Presented automatically after approval, including existing installs. Every feature remains a choice. */
    private fun sharingSetup() {
        val step = prefs.getInt("sharing_setup_step", 0).coerceIn(0, 2)
        val access = sefirah.network.orion.OrionPermissions.read(this)
        root.addView(text("Sharing setup · ${step + 1} of 3", UiType.META, Palette.MUTED))
        root.addView(heading(listOf("Your photos, on your computer", "Your phone notifications", "Your texts and calls")[step]).apply { setPadding(0, dp(8), 0, 0) })
        root.addView(body(listOf("Choose which photos your approved computers can see.", "Allow Saiph notification access in Android Settings.", "Read and send texts. Handle calls with audio on your phone.")[step])
            .apply { setPadding(0, dp(8), 0, dp(4)) })
        // One Allow action per step, so the screen shows what that tap leads to.
        root.addView(when (step) {
            0 -> stepGuide(Step(StepPicture.VERIFY, "Confirm it's you."), Step(StepPicture.ALLOW, "Choose which photos Android lets Saiph see."),
                Step(StepPicture.NOTIFY, "Your approved computers show those photos."))
            1 -> stepGuide(Step(StepPicture.ALLOW, "In Android Settings, turn on notification access for Saiph."),
                Step(StepPicture.NOTIFY, "This phone's notifications appear on your computers."))
            else -> stepGuide(Step(StepPicture.VERIFY, "Confirm it's you."), Step(StepPicture.ALLOW, "Allow texts, calls and contacts in Android."),
                Step(StepPicture.COMPUTER_TAB, "Read, reply and answer calls in Saiph on your computer. Call audio stays on this phone."))
        })
        val allowed = when (step) {
            0 -> runtime.photosShared() && access.photos
            1 -> access.notifications
            else -> runtime.textsAndCalls() && PHONE_PERMISSIONS.all(::granted)
        }
        if (allowed) root.addView(badge("Allowed", Palette.GOOD, Palette.GOOD_SURFACE))
        else dockActions(button(listOf("Allow photo gallery", "Allow notifications", "Allow texts and calls")[step], true) {
            when (step) { 0 -> allowPhotos(); 1 -> notificationAccess(); else -> allowPhone() }
        })
        dockActions(button(if (step == 2 && allowed) "Finish setup" else if (allowed) "Continue" else "Not now", primary = allowed) {
            check(prefs.edit().putInt("sharing_setup_step", step + 1).putBoolean("sharing_setup_complete", step == 2).commit())
            render()
        })
    }
    /**
     * Photo gallery on or off. Turning it on needs the owner and Android's photo access, so the
     * switch stays off until both are settled; the screen redraws then.
     */
    private fun LinearLayout.photoSwitch() {
        val access = sefirah.network.orion.OrionPermissions.read(this@HostedActivity).photos
        addView(settingSwitch("Photo gallery", "Recent photos on your computers.", runtime.photosShared()) { view, on ->
            if (on == runtime.photosShared()) return@settingSwitch
            if (on) { view.isChecked = false; allowPhotos() } else { runtime.setPhotosShared(false); render() }
        }.apply {
            if (runtime.photosShared()) addView(compactActions(
                if (access) compactButton("Choose photos") { requestSharingPermissions("photos") }
                else compactButton("Allow photo access") { requestSharingPermissions("photos") }))
        })
    }
    /** Off by default: approved computers may act on texts and calls only after the owner turns this on here. */
    private fun textsAndCalls() = group("Texts and calls") {
        val on = runtime.textsAndCalls()
        addView(settingSwitch("Texts and calls", "On your computers. Call audio stays on this phone.", on) { view, checked ->
            if (checked == runtime.textsAndCalls()) return@settingSwitch
            // Unchanged until the owner is verified and Android access is settled; the screen redraws then.
            if (checked) { view.isChecked = false; allowPhone() } else { runtime.setTextsAndCalls(false); render() }
        })
        if (on && PHONE_PERMISSIONS.any { !granted(it) }) {
            addView(text("Some Android access is missing.", UiType.META, Palette.WARN).apply { setPadding(0, dp(4), 0, 0) })
            addView(compactActions(compactButton("Allow access") { allowPhone() }))
        }
        addView(disclosure("Learn more") {
            addView(featureRow(sefirah.common.R.drawable.ic_chat, "Texts", "Read and reply to one-to-one texts, or start one."))
            addView(featureRow(sefirah.common.R.drawable.ic_call, "Calls", "Answer, decline or dial from your computer."))
            addView(text("Every approved computer on your account can use these while this is on.", UiType.META, Palette.MUTED).apply { setPadding(0, dp(4), 0, 0) })
        })
    }
    /** On by default, like Phone Link: battery, network and sound in the computer's header, with its quick actions. */
    private fun statusAndControls() = group("Status and quick controls") {
        val shared = runtime.statusShared()
        addView(settingSwitch("Share phone status", "Battery, signal and sound mode on your computers.", shared) { _, checked ->
            if (checked != runtime.statusShared()) { runtime.setStatusShared(checked); render() }
        })
        if (shared) {
            if (!sefirah.network.orion.PhoneQuickControls.policyAccess(this@HostedActivity)) {
                addView(text("Sound mode and Do Not Disturb need Do Not Disturb access.", UiType.META, Palette.MUTED).apply { setPadding(0, dp(4), 0, 0) })
                addView(compactActions(compactButton("Allow Do Not Disturb access") {
                    openSharingSettings(Intent(Settings.ACTION_NOTIFICATION_POLICY_ACCESS_SETTINGS))
                }))
            }
            if (!sefirah.network.orion.OrionPermissions.read(this@HostedActivity).notifications)
                addView(text("Music controls need notification access.", UiType.META, Palette.MUTED).apply { setPadding(0, dp(8), 0, 0) })
        }
        addView(divider())
        addView(settingSwitch("Sync over mobile data", if (runtime.mobileDataAllowed()) "Also syncs on mobile data." else "Wi-Fi only. Pauses on metered networks.",
            runtime.mobileDataAllowed()) { _, checked ->
            if (checked != runtime.mobileDataAllowed()) { runtime.setMobileData(checked); render() }
        })
        addView(disclosure("Learn more") {
            addView(featureRow(sefirah.common.R.drawable.ic_battery, "Phone status", "Battery, Wi-Fi, Bluetooth, signal and sound mode."))
            addView(featureRow(sefirah.common.R.drawable.ic_volume_up_fill, "Quick actions", "Find phone, sound mode, Do Not Disturb and music."))
        })
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
        val enrolled = prefs.contains("device_id")
        if (enrolled || account.signedIn()) welcomePage = false
        // A recreated activity may outlive an interrupted enrollment job.
        // Never keep comparing a second root once local identity intent exists.
        if (enrolled && !busy) { pendingRoot = null; cancelNearby() }
        shownStage = runtime.setupStage()
        val page = when {
            pendingRoot != null -> "confirm"
            nearbyRoot != null -> "nearby"
            nearbyChoices != null -> "choose"
            settingsPage -> "settings" + (settingsCategory?.let { ":" + it.name } ?: "")
            shownStage == HostedSetup.Stage.RECOVERY -> "recovery"
            welcomePage || (!enrolled && !account.signedIn()) -> "welcome"
            waitingForApproval() -> "waiting"
            !runtime.enabled() -> "paused"
            HostedSharing.needsSetup(shownStage == HostedSetup.Stage.HOME, prefs.getBoolean("sharing_setup_complete", false)) -> "sharing"
            enrolled -> "home"
            else -> "connect"
        }
        shell(if (settingsPage) settingsCategory?.title ?: "Settings" else "Saiph", page)
        if (busy) {
            // Keep comparison on screen until its action finishes; reject double taps.
            val currentFrame = window.decorView
            currentFrame.post {
                fun disable(view: android.view.View) {
                    if (view is Button || view is ImageButton) view.isEnabled = false
                    if (view is android.view.ViewGroup) for (i in 0 until view.childCount) disable(view.getChildAt(i))
                }
                if (busy) disable(currentFrame)
            }
            root.addView(text("Connecting…", UiType.BODY))
        }
        if (actionError.isNotEmpty()) root.addView(text(actionError, UiType.BODY, Palette.WARN).apply {
            accessibilityLiveRegion = android.view.View.ACCESSIBILITY_LIVE_REGION_POLITE
            setPadding(0, dp(8), 0, dp(16))
        })
        status = text(statusLine(), UiType.META, Palette.MUTED).apply { setPadding(dp(2), 0, 0, dp(6)); visibility = if (text.isEmpty() || page == "welcome") android.view.View.GONE else android.view.View.VISIBLE }; root.addView(status)
        if (getSharedPreferences("orion", 0).contains("device_id")) {
            root.addView(card().apply { addView(text("This phone is paired with a self-hosted Hub. Use an unpaired phone for a Saiph account.", UiType.BODY)) }); return
        }
        if (!enrolled && !account.signedIn() && !AppPolicy.acknowledged(this)) {
            policyScreen(); return
        }
        pendingRoot?.let { confirmRootScreen(it); return }
        if (nearbyRoot != null) { nearbyScreen(); return }
        nearbyChoices?.let { chooseComputerScreen(it); return }
        if (settingsPage) { hostedSettings(); return }
        if (shownStage == HostedSetup.Stage.RECOVERY) { recoveryScreen(); return }
        if (shownStage == HostedSetup.Stage.HOME && runtime.enabled() && !account.signedIn()) {
            root.addView(card(strong = true).apply {
                addView(cardTitle("Sign in to resume syncing"))
                addView(body("Your computer's approval is kept."))
                if (loginError.isNotEmpty()) addView(text(loginError, UiType.BODY, Palette.WARN))
                actions(button(if (signingIn) "Waiting for sign-in…" else "Continue with Google", true) { signIn() }.apply { isEnabled = !signingIn })
            })
            return
        }
        // Free trial days left, or why Cloud is paused, with a way to subscribe.
        if (account.signedIn() && !settingsPage) trialNotice()
        // Account expiry does not erase device approval or return to the welcome menu.
        shownWaiting = waitingForApproval()
        if (welcomePage || (!enrolled && !account.signedIn())) {
            signInScreen(enrolled)
            return
        }
        if (shownWaiting) {
            waitingScreen()
            return
        }
        if (page == "sharing") { sharingSetup(); return }
        if (!runtime.enabled()) {
            root.addView(card(strong = true).apply {
                addView(text("Sync is turned off on this phone. Your account and device approval are kept.", UiType.BODY))
                actions(button("Resume syncing", true) { toggleHosted() })
            })
            if (enrolled) retirementAction()
        } else if (enrolled) {
            // Daily use first: the features people start, then what is shared.
            shownOffers = receivedKeys()
            lanLines.clear()
            root.addView(quickActions(
                QuickAction(sefirah.common.R.drawable.ic_videocam, "Use as webcam") { startActivity(Intent(this@HostedActivity, PhoneCameraActivity::class.java)) },
                QuickAction(sefirah.common.R.drawable.ic_desktop_windows, "Share screen") { startActivity(Intent(this@HostedActivity, PhoneScreenActivity::class.java)) },
                QuickAction(sefirah.common.R.drawable.ic_upload, "Send a file") { sendFile.launch(arrayOf("*/*")) }))
            group("Photos and files") {
                photoSwitch()
                addView(divider())
                addView(text("Received files", UiType.BODY, bold = true).apply { androidx.core.view.ViewCompat.setAccessibilityHeading(this, true) })
                val direct = runtime.lanReceived()
                if (runtime.offers.isEmpty() && direct.isEmpty()) addView(text("Files from your computers appear here.", UiType.META, Palette.MUTED).apply { setPadding(0, dp(4), 0, 0) })
                // Files received over the local network: progress, then the same Save choices; a failure says why.
                direct.forEachIndexed { index, item ->
                    if (index > 0) addView(divider())
                    addView(text(item.name).apply { setPadding(0, dp(8), 0, 0) })
                    addView(text(lanLine(item), UiType.META, if (item.state == "failed") Palette.TEXT else Palette.MUTED).also { lanLines[item.id] = it })
                    val id = "lan:" + item.id
                    when {
                        item.state == "ready" && android.os.Build.VERSION.SDK_INT >= 29 -> addView(compactActions(compactButton("Save to Downloads") {
                            action { val saved = runtime.saveToDownloads(id); withContext(Dispatchers.Main) { message(HostedTransferText.saved(saved)); render() } }
                        }.apply { contentDescription = "Save ${item.name} to Downloads" },
                            compactButton("Save as…") { saving = id; saveFile.launch(item.name) }.apply { contentDescription = "Save ${item.name} as" }))
                        item.state == "ready" -> addView(compactActions(compactButton("Save file") { saving = id; saveFile.launch(item.name) }.apply { contentDescription = "Save ${item.name}" }))
                        else -> addView(compactActions(compactButton(if (item.state == "failed") "Dismiss" else "Stop") { runtime.dismissReceived(id); render() }
                            .apply { contentDescription = (if (item.state == "failed") "Dismiss " else "Stop receiving ") + item.name }))
                    }
                }
                runtime.offers.forEachIndexed { index, (id, name) ->
                    if (index > 0 || direct.isNotEmpty()) addView(divider())
                    addView(text(name).apply { setPadding(0, dp(8), 0, 0) })
                    // One tap saves to Downloads → Saiph; Save as… still lets the owner choose.
                    if (android.os.Build.VERSION.SDK_INT >= 29) {
                        addView(compactActions(compactButton("Save to Downloads") {
                            action { val saved = runtime.saveToDownloads(id); withContext(Dispatchers.Main) { message(HostedTransferText.saved(saved)) } }
                        }.apply { contentDescription = "Save $name to Downloads" },
                            compactButton("Save as…") { saving = id; saveFile.launch(name) }.apply { contentDescription = "Save $name as" }))
                    } else addView(compactActions(compactButton("Save file") { saving = id; saveFile.launch(name) }.apply { contentDescription = "Save $name" }))
                }
            }
            textsAndCalls()
            statusAndControls()
            group("Phone notifications") {
                val allowed = sefirah.network.orion.OrionPermissions.read(this@HostedActivity).notifications
                addView(settingsRow(sefirah.common.R.drawable.ic_notifications, if (allowed) "Shared with your computers" else "Show them on your computers",
                    if (allowed) "Manage in Android settings" else "Allow notification access", external = true) { notificationAccess() })
            }
        } else {
            root.addView(setupProgress(1))
            setupIntro(SetupArtwork.Scene.SCAN, "Connect to your computer", "On your computer: Saiph → Phone → Add a device. On the same Wi-Fi, find it here; otherwise scan its QR code.")
            if (searching) root.addView(text("Looking for your computer on this Wi-Fi…", UiType.BODY).apply {
                accessibilityLiveRegion = android.view.View.ACCESSIBILITY_LIVE_REGION_POLITE })
            root.addView(disclosure("Paste a code instead") {
                val code = field("Computer code", into = this)
                actions(button("Check code", tone = Tone.TONAL) { checkRoot(code.text.toString()) })
            })
            dockActions(button(if (searching) "Looking…" else "Find my computer", true) { findComputer() }.apply { isEnabled = !searching },
                button("Scan QR code", tone = Tone.TONAL) { scanRoot.launch(OrionQrActivity.hostedRoot(this@HostedActivity)) })
            setupDock.addView(buttonRow(setupLink("Use a different account") { action { account.signOut() } }))
        }
    }
    /** Settings: search and a list of categories, or one category's page (SettingsCatalog.CLOUD). */
    private fun hostedSettings() {
        val entries = SettingsCatalog.CLOUD.filter { it.id != "usage" || UsageAnalytics.available(this) }
        val category = settingsCategory
        if (category == null) {
            root.addView(settingsHome(entries, settingsQuery, { settingsQuery = it }, { settingsCategory = it; render() }) { entry ->
                settingsCategory = entry.category; settingsTarget = entry.id; render()
            })
            return
        }
        val page = SettingsPage(root, entries)
        val enrolled = prefs.contains("device_id")
        val syncing = runtime.enabled()
        // In place of controls that need an approved, syncing phone, so a search never lands on nothing.
        fun later(id: String) = page.item(id, if (!enrolled) "Available once this phone is connected to your computer." else "Turn on sync in Connection to change this.")
        fun androidSettings(target: Intent) { runCatching { startActivity(target) }.onFailure { message("Open Android Settings to manage Saiph permissions.") } }
        when (category) {
            SettingsCatalog.Category.ACCOUNT -> {
                page.linkItem("subscription", "Plans and billing on your Saiph account page", external = true) { openPolicy(HostedSignIn.PLANS_URL) }
                if (syncing) page.item("sign_in", if (account.signedIn()) "Signed in to your Saiph account." else "Sign in again to resume syncing. Your device approval is kept.") {
                    if (account.signedIn()) addView(compactActions(compactButton("Sign out", Tone.SECONDARY) { action { account.signOut() } }))
                    else {
                        addView(compactActions(compactButton(if (signingIn) "Waiting for sign-in…" else "Sign in to Saiph", Tone.SECONDARY) { signIn() }.apply { isEnabled = !signingIn }))
                        if (loginError.isNotEmpty()) {
                            addView(text(loginError, UiType.BODY, Palette.WARN).apply { setPadding(0, dp(8), 0, 0) })
                            addView(compactActions(compactButton("Use browser app instead") { signIn(browserApp = true) }.apply { isEnabled = !signingIn }))
                        }
                    }
                }
                if (!enrolled) page.item("own_hub", "Use a Saiph Hub you run yourself instead of a Saiph account.") {
                    addView(compactActions(compactButton("Connect my own Hub") { useOwnHub() }))
                } else page.item("own_hub", "To switch to your own Hub, turn off sync and remove this phone first.")
                if (enrolled) {
                    page.item("this_phone", "Full device fingerprint") {
                        addView(text(runtime.fingerprint, UiType.META).apply { setPadding(0, dp(8), 0, 0); setTextIsSelectable(true) })
                        addView(compactActions(compactButton("Create a fresh request") { verified("Show a request to add this phone") { action { runtime.freshRequest() } } }.apply { isEnabled = runtime.enabled() }))
                        if (runtime.requestCode.isNotEmpty()) addView(disclosure("View approval request code") {
                            addView(body("Paste this request into your computer. Compare every fingerprint group before approving.").apply { setPadding(0, dp(12), 0, dp(8)) })
                            addView(context.field("Phone device approval request code").apply { setText(runtime.requestCode); isFocusable = false; contentDescription = "Phone device approval request code" })
                        })
                    }
                    page.item("remove_phone", "Also remove it on your main computer. Its encrypted keys and trust history stay on this phone for recovery.") {
                        addView(compactActions(compactButton("Remove this phone from your account", Tone.DANGER) { confirmRetire() }))
                    }
                }
            }
            SettingsCatalog.Category.CONNECTION -> {
                page.switchItem("sync", if (syncing) "Turning sync off keeps your account and device approval." else "Sync is off. Your account and device approval are kept.", syncing) { _, on ->
                    if (on != runtime.enabled()) toggleHosted()
                }
                if (syncing && enrolled) page.linkItem("background", "Manage battery restrictions. Android may limit clipboard access in the background.", external = true) {
                    androidSettings(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName")))
                } else later("background")
            }
            SettingsCatalog.Category.NOTIFICATIONS -> if (syncing && enrolled) {
                val allowed = sefirah.network.orion.OrionPermissions.read(this).notifications
                page.linkItem("notification_access", if (allowed) "Allowed. Your computers show this phone's notifications." else "Allow Saiph to share notifications with your computers.", external = true) { notificationAccess() }
                page.linkItem("saiph_alerts", "Choose which Saiph status alerts appear on this phone.", external = true) {
                    androidSettings(Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, packageName))
                }
            } else { later("notification_access"); later("saiph_alerts") }
            SettingsCatalog.Category.MESSAGES -> if (enrolled && syncing) {
                val missing = PHONE_PERMISSIONS.filterNot(::granted)
                page.switchItem("texts_and_calls", "Read and reply to texts, and answer, decline or dial calls from your computer. Audio stays on your phone. Every approved computer on your account can use these features.",
                    runtime.textsAndCalls(), build = {
                        if (runtime.textsAndCalls() && missing.isNotEmpty()) {
                            addView(text("Some Android access is missing. Allow it to use all text and call features.", UiType.META, Palette.WARN).apply { setPadding(0, dp(4), 0, 0) })
                            addView(compactActions(compactButton("Allow texts and calls") { allowPhone() }))
                        }
                    }) { view, on ->
                    if (on == runtime.textsAndCalls()) return@switchItem
                    // Unchanged until the owner is verified and Android access is settled; the page redraws then.
                    if (on) { view.isChecked = false; allowPhone() } else { runtime.setTextsAndCalls(false); render() }
                }
            } else later("texts_and_calls")
            SettingsCatalog.Category.PHOTOS -> if (enrolled && syncing) {
                val access = sefirah.network.orion.OrionPermissions.read(this).photos
                page.switchItem("photo_gallery", "Recent photos on your computers. You choose which photos Android allows.", runtime.photosShared(), build = {
                    if (runtime.photosShared()) addView(compactActions(
                        if (access) compactButton("Manage photo access") { requestSharingPermissions("photos") }
                        else compactButton("Allow photo gallery") { requestSharingPermissions("photos") }))
                }) { view, on ->
                    if (on == runtime.photosShared()) return@switchItem
                    if (on) { view.isChecked = false; allowPhotos() } else { runtime.setPhotosShared(false); render() }
                }
            } else later("photo_gallery")
            SettingsCatalog.Category.CLIPBOARD -> {
                val shared = getSharedPreferences("orion", 0)
                page.switchItem("clipboard", "Copy on one device and paste on another. Android may limit clipboard access while Saiph is in the background.",
                    shared.getBoolean("clipboard_enabled", true), build = {
                        runtime.clipboardNotice.takeIf { it.isNotEmpty() }?.let { addView(text(it, UiType.META, Palette.WARN).apply { setPadding(0, dp(4), 0, 0) }) }
                    }) { _, on -> shared.edit().putBoolean("clipboard_enabled", on).apply(); runtime.wake.trySend(Unit) }
            }
            SettingsCatalog.Category.CAMERA -> {
                page.linkItem("webcam", "Use this phone's camera on your computer over the same Wi-Fi.") {
                    startActivity(Intent(this, PhoneCameraActivity::class.java))
                }
                page.linkItem("camera_access", if (granted(Manifest.permission.CAMERA)) "Allowed. Manage it in Android settings." else "Off. Saiph asks when you start the camera.", external = true) {
                    androidSettings(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName")))
                }
            }
            SettingsCatalog.Category.STATUS -> page.switchItem("status_sharing", "Battery, Wi-Fi, Bluetooth, signal and sound mode on your computers, and their quick actions: find this phone, sound mode and Do Not Disturb.",
                runtime.statusShared()) { _, on -> runtime.setStatusShared(on) }
            SettingsCatalog.Category.PRIVACY -> {
                page.item("app_lock") { addView(lock.toggle()) }
                val events = runtime.securityEvents()
                page.item("security_activity", if (events.isEmpty()) "No devices have been added or removed yet." else "Devices added to or removed from your account.") {
                    events.forEach { addView(text(it, UiType.META, Palette.MUTED).apply { setPadding(0, dp(4), 0, 0) }) }
                }
                if (UsageAnalytics.available(this)) page.item("usage") { UsageAnalytics.settingsControls(this@HostedActivity).forEach(::addView) }
                page.item("policies") {
                    addView(settingsRow(null, "Privacy policy", null, external = true) { openPolicy(AppPolicy.PRIVACY_URL) })
                    addView(settingsRow(null, "Terms", null, external = true) { openPolicy(AppPolicy.TERMS_URL) })
                }
            }
            SettingsCatalog.Category.ABOUT -> page.item("updates", "Saiph ${com.castle.sefirah.BuildConfig.VERSION_NAME} (build ${com.castle.sefirah.BuildConfig.VERSION_CODE}). Updates come from your Saiph account.") {
                updateSettings().forEach(::addView)
            }
        }
        settingsTarget.takeIf { it.isNotEmpty() }?.let { page.reveal(it, scroll) }
        settingsTarget = ""
    }
    private fun trialNotice() {
        val notice = HostedTrial.notice(runtime.access, System.currentTimeMillis() / 1000) ?: return
        root.addView(card(strong = notice.state != "trial").apply {
            addView(cardTitle(notice.title))
            addView(body(notice.message))
            actions(button(notice.action, notice.state != "trial") {
                runCatching { startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(HostedSignIn.PLANS_URL))) }
                    .onFailure { message("Enable a browser to view Saiph plans.") }
            })
        })
    }
    /** One welcome screen owns the plan, sign-in and self-hosted routes. */
    private fun signInScreen(enrolled: Boolean) {
        root.addView(setupProgress(0))
        setupIntro(SetupArtwork.Scene.WELCOME, if (enrolled) "Finish connecting" else "Your devices. Connected.",
            if (signingIn) "Finish signing in, then return here." else if (enrolled) "Your phone is waiting for approval." else "Your phone and computer, together.")
        if (loginError.isNotEmpty()) {
            root.addView(text(loginError, UiType.BODY, Palette.WARN).apply { accessibilityLiveRegion = android.view.View.ACCESSIBILITY_LIVE_REGION_POLITE })
            actionsOnRoot(button("Use browser app instead", tone = Tone.TONAL) { signIn(browserApp = true, google = googleSignIn) }.apply { isEnabled = !signingIn })
        }
        val signedIn = account.signedIn()
        if (!signedIn && !enrolled) dockActions(button("Subscribe", true) {
            runCatching { startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(HostedSignIn.PLANS_URL))) }
                .onFailure { message("Enable a browser to view Saiph plans.") }
        })
        dockActions(button(if (signingIn) "Waiting for sign-in…" else if (signedIn) "Continue setup" else "Continue with Google", primary = signedIn) { signIn(google = true) }.apply { isEnabled = !signingIn })
        if (!enrolled) setupDock.addView(buttonRow(setupLink("Self-hosted") { useOwnHub() }.apply { isEnabled = !signingIn }))
        if (!signedIn && !enrolled) root.addView(disclosure("Other sign-in options") {
            addView(body("Use your existing sign-in method to keep the same account."))
            actions(button("Use email or another provider", tone = Tone.TONAL) { signIn(google = false) }.apply { isEnabled = !signingIn })
            addView(body("Start your free trial (no card needed) or activate an invitation on your Saiph account page, then continue with that account."))
        })
        if (!runtime.enabled() && !enrolled) {
            // Custom builds retain manual configuration outside the normal account flow.
            if (!runtime.hasPackagedDefaults()) {
                root.addView(disclosure("Custom service (advanced)") {
                    val origin = field("Cloud service address", prefs.getString("origin", "")!!, this)
                    val issuer = field("Sign-in issuer (HTTPS, ending in /)", prefs.getString("issuer", "")!!, this)
                    val audience = field("API audience", prefs.getString("audience", "")!!, this)
                    val client = field("Android native client ID", prefs.getString("client_id", "")!!, this)
                    val refresh = CheckBox(context).apply { text = "Keep me signed in with a protected rotating refresh token"; isChecked = prefs.getBoolean("refresh_tokens", false); setTextColor(Palette.TEXT); buttonTintList = android.content.res.ColorStateList.valueOf(Palette.ACCENT) }; addView(refresh)
                    actions(button("Save custom service") { verified("Change the custom service settings", requireScreenLock = false) {
                        action { runtime.configure(origin.text.toString(), issuer.text.toString(), audience.text.toString(), client.text.toString(), refresh.isChecked) }
                    } })
                })
            }
        }
        if (!runtime.enabled() && enrolled) retirementAction()
    }
    /** Switching an unpaired phone is explicit; stop the account service before Hub pairing. */
    private fun useOwnHub() {
        if (prefs.contains("device_id") || signingIn) return
        lifecycleScope.launch {
            try {
                withContext(Dispatchers.IO) { account.signOut(); runtime.setEnabled(false) }
                stopService(Intent(this@HostedActivity, HostedSyncService::class.java))
                getSharedPreferences("orion", 0).edit().putBoolean("self_host", true).apply()
                startActivity(Intent(this@HostedActivity, OrionActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP))
                finish()
            } catch (failure: CancellationException) { throw failure }
            catch (_: Exception) { message("Could not switch connection. Try again.") }
        }
    }
    /** What the received-files list shows; a change redraws it. Progress alone only updates its line. */
    private fun receivedKeys() = runtime.offers.map { it.first } + runtime.lanReceived().map { it.id + ":" + it.state }
    private fun lanLine(item: LanTransfers.Incoming) = when (item.state) {
        "receiving" -> "Receiving from ${item.computer} over your network · ${if (item.size > 0) item.received * 100 / item.size else 100}%"
        "failed" -> item.error
        else -> "Received over your network · ${HostedTransferText.megabytes(item.size, up = true)} MB"
    }
    private fun statusLine() = when {
        account.signedIn() -> runtime.status + " · Signed in" + runtime.clipboardNotice.takeIf { it.isNotEmpty() }?.let { " · $it" }.orEmpty() +
            runtime.lan.sending?.let { " · " + HostedTransferText.sending(it.name, it.computer, it.sent, it.size, it.connecting) }.orEmpty()
        prefs.contains("device_id") -> runtime.status
        else -> ""
    }
    private fun waitingForApproval() = runtime.enabled() && runtime.setupStage() == HostedSetup.Stage.APPROVAL
    private fun recoveryScreen() {
        root.addView(card(strong = true).apply {
            addView(cardTitle("Finish connecting this phone"))
            addView(body("The earlier setup could not finish. Start a new connection to your computer."))
            actions(button("Restart setup", true) {
                android.app.AlertDialog.Builder(this@HostedActivity).setTitle("Restart setup?")
                    .setMessage("Your account stays signed in and the earlier keys are kept. Scan your computer's QR code again. If this phone already appears there, remove its old entry.")
                    .setNegativeButton("Cancel", null).setPositiveButton("Restart") { _, _ ->
                        verified("Restart connecting this phone") { action { runtime.restartSetup(); settingsPage = false } }
                    }.show()
            })
            actions(button(if (account.signedIn()) "Retry connection" else "Continue with Google", tone = Tone.TONAL) {
                if (!account.signedIn()) signIn() else action { runtime.freshRequest() }
            })
        })
    }
    /** One job while the computer has not approved this phone yet: compare and approve there. */
    private fun waitingScreen() {
        root.addView(setupProgress(2))
        root.addView(SetupArtwork(this, SetupArtwork.Scene.APPROVE).apply { layoutParams.height = dp(156) })
        root.addView(card(strong = true).apply {
            addView(cardTitle("Approve this phone"))
            addView(body(if (nearbyCompared.isNotEmpty() && nearbyDelivered) "On your computer, check the code $nearbyCompared again and choose Codes match, approve."
                else "On your computer, compare every group of this code and approve."))
            if (runtime.fingerprint.isNotEmpty()) addView(securityCode(runtime.fingerprint))
            addView(text("Waiting for your computer…", UiType.META, Palette.MUTED))
            addView(disclosure("Phone not appearing?") {
                actions(button("Send a fresh request", tone = Tone.TONAL) {
                    if (!account.signedIn()) signIn() else verified("Show a request to add this phone") { action { runtime.freshRequest() } }
                })
                if (runtime.requestCode.isNotEmpty()) actions(button("Share the request code instead", tone = Tone.TONAL) {
                    // Only public keys and a signature: safe to send to yourself if the computer cannot see the request.
                    runCatching { startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, runtime.requestCode), "Share request code")) }
                })
            })
            if (loginError.isNotEmpty()) addView(text(loginError, UiType.BODY, Palette.WARN))
        })
        retirementAction()
    }
    private fun actionsOnRoot(vararg buttons: Button) = root.addView(buttonRow(*buttons))
    private fun openPolicy(url: String) {
        runCatching { startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url))) }
            .onFailure { message("Enable a browser to open this page.") }
    }
    private fun policyScreen() {
        root.addView(SetupArtwork(this, SetupArtwork.Scene.WELCOME))
        root.addView(heading("Before you start"))
        root.addView(body("Review how Saiph handles your data. Cloud terms apply if you use Saiph Cloud."))
        actionsOnRoot(button("Privacy policy", tone = Tone.TONAL) { openPolicy(AppPolicy.PRIVACY_URL) },
            button("Cloud terms", tone = Tone.TONAL) { openPolicy(AppPolicy.TERMS_URL) })
        root.addView(body("By continuing, you acknowledge the privacy policy and agree to the terms when using Cloud. Sharing usage statistics is a separate choice."))
        dockActions(button("Agree and continue", true) { AppPolicy.acknowledge(this); render() })
        setupDock.addView(buttonRow(setupLink("Exit") { finish() }))
    }
    private fun retirementAction() = actionsOnRoot(button("Remove this phone from your account", tone = Tone.DANGER) { confirmRetire() })
    private fun confirmRetire() {
        android.app.AlertDialog.Builder(this).setTitle("Remove this phone from your account?").setMessage("Also remove it on your main computer. Its encrypted keys and trust history stay on this phone for recovery.")
            .setNegativeButton("Cancel", null).setPositiveButton("Remove") { _, _ -> verified("Remove this phone from your account", requireScreenLock = false) { action {
                runtime.mutex.withLock {
                    runtime.setEnabled(false)
                    stopService(Intent(this@HostedActivity, HostedSyncService::class.java))
                    runtime.retire()
                }
                settingsPage = false; settingsCategory = null
            } } }.show()
    }
    /** One switch for the whole service; starting it also applies this build's connection defaults. */
    private fun toggleHosted() = action {
        val enabled = !runtime.enabled()
        if (enabled) runtime.applyPackagedDefaults()
        runtime.setEnabled(enabled)
        if (enabled) ContextCompat.startForegroundService(this@HostedActivity, Intent(this@HostedActivity, HostedSyncService::class.java)) else stopService(Intent(this@HostedActivity, HostedSyncService::class.java))
    }
}
