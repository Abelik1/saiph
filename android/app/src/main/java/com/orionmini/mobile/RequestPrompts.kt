// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.app.Activity
import android.app.Application
import android.app.Dialog
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.graphics.drawable.ColorDrawable
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.ViewGroup
import android.view.Window
import android.view.WindowManager
import android.widget.ImageView
import android.widget.LinearLayout
import java.lang.ref.WeakReference

/**
 * Which computer requests are prompting the owner, and on which surfaces. Pure, so the
 * JVM tests cover it: one prompt per service (a newer offer replaces an older one), a
 * pop-up only while Saiph is in the foreground, and every prompt removed when its
 * offer is taken, closed by its computer, declined or expired.
 */
internal class RequestBoard {
    data class Prompt(val id: String, val service: String, val computer: String, val expiresAt: Long)
    data class Plan(val notify: Boolean, val popup: Boolean, val replaced: List<Prompt>)

    private val prompts = LinkedHashMap<String, Prompt>()
    private val hidden = HashSet<String>()

    @Synchronized fun offer(prompt: Prompt, foreground: Boolean, now: Long): Plan {
        expire(now)
        val replaced = prompts.values.filter { it.service == prompt.service && it.id != prompt.id }
        replaced.forEach { prompts.remove(it.id); hidden.remove(it.id) }
        if (prompt.expiresAt <= now) return Plan(notify = false, popup = false, replaced = replaced)
        prompts[prompt.id] = prompt
        return Plan(notify = true, popup = foreground, replaced = replaced)
    }
    /** The prompt for [id], removed; null when there is none (already replaced or gone). */
    @Synchronized fun close(id: String): Prompt? { hidden.remove(id); return prompts.remove(id) }
    /** The owner opened or started this service: its prompts go. */
    @Synchronized fun take(service: String): List<Prompt> = remove { it.service == service }
    @Synchronized fun expire(now: Long): List<Prompt> = remove { it.expiresAt <= now }
    /** Offers the runtime no longer holds (revoked computer, sign-out). */
    @Synchronized fun retain(ids: Set<String>): List<Prompt> = remove { it.id !in ids }
    /** Back or a tap outside the pop-up: keep the notification, do not pop up again. */
    @Synchronized fun hide(id: String) { if (id in prompts) hidden += id }
    @Synchronized fun get(id: String): Prompt? = prompts[id]
    /** The newest prompt that may still pop up when Saiph comes to the foreground. */
    @Synchronized fun popupCandidate(now: Long): Prompt? { expire(now); return prompts.values.lastOrNull { it.id !in hidden } }
    @Synchronized fun current(service: String): Prompt? = prompts.values.lastOrNull { it.service == service }

    private fun remove(test: (Prompt) -> Boolean): List<Prompt> {
        val gone = prompts.values.filter(test)
        gone.forEach { prompts.remove(it.id); hidden.remove(it.id) }
        return gone
    }

    companion object {
        /** Title and body of the pop-up and notification for one request. */
        fun copy(service: String, computer: String): Pair<String, String> {
            val name = computer.trim().take(40).ifEmpty { "Your computer" }
            return if (service == "camera") "$name wants to use your camera" to
                "Allow to confirm it's you, then your camera starts for $name. Audio stays off."
            else "$name wants to show your screen" to
                "Allow to confirm it's you, then choose Start now. $name sees this screen until you stop; protected screens stay black."
        }
    }
}

/** The resumed activity, if Saiph is in the foreground. Registered once by the application. */
internal object ForegroundActivity : Application.ActivityLifecycleCallbacks {
    private var current: WeakReference<Activity>? = null
    fun register(application: Application) = application.registerActivityLifecycleCallbacks(this)
    fun current(): Activity? = current?.get()?.takeIf { !it.isFinishing && !it.isDestroyed }
    override fun onActivityResumed(activity: Activity) { current = WeakReference(activity); RequestPrompts.resumed(activity) }
    override fun onActivityPaused(activity: Activity) { if (current?.get() === activity) current = null; RequestPrompts.paused(activity) }
    override fun onActivityCreated(activity: Activity, state: Bundle?) = Unit
    override fun onActivityStarted(activity: Activity) = Unit
    override fun onActivityStopped(activity: Activity) = Unit
    override fun onActivitySaveInstanceState(activity: Activity, state: Bundle) = Unit
    override fun onActivityDestroyed(activity: Activity) = Unit
}

/**
 * Camera and phone screen requests from a computer (docs/PHONE_SCREEN.md, PHONE_CAMERA.md).
 * Always a high-priority notification, which Android shows as heads-up outside Saiph; while
 * Saiph is open, also an in-app pop-up. Allow opens the camera or screen page, which asks for
 * owner verification before anything starts; Not now drops the offer. Both disappear when the
 * offer is taken, its computer closes it (`session.close`), it is revoked or it expires.
 * No full-screen intent: Android 14 reserves that for calls and alarms.
 */
internal object RequestPrompts {
    const val EXTRA_ALLOW = "request_allow"
    private val board = RequestBoard()
    private val main = Handler(Looper.getMainLooper())
    private var dialog: Dialog? = null
    private var dialogId: String? = null

    private fun now() = System.currentTimeMillis() / 1000

    fun show(context: Context, offer: SessionOffer, computer: String) {
        val app = context.applicationContext
        val prompt = RequestBoard.Prompt(offer.id, offer.service, computer, offer.expiresAt)
        main.post {
            val activity = ForegroundActivity.current()?.takeIf { !AppLock.locked(it) }
            val plan = board.offer(prompt, activity != null, now())
            plan.replaced.forEach { if (dialogId == it.id) dismissPopup() }
            if (plan.notify) notify(app, offer, computer)
            if (plan.popup && activity != null) popup(activity, prompt)
            main.postDelayed({ expire(app) }, ((offer.expiresAt - now()) * 1000 + 500).coerceIn(500, SessionOffer.MAX_LIFETIME * 1000 + 500))
        }
    }

    /** The computer closed offer [id]: it was answered elsewhere, cancelled or expired. */
    fun closed(context: Context, id: String) {
        val app = context.applicationContext
        main.post { board.close(id)?.let { cancel(app, it.service); if (dialogId == id) dismissPopup() } }
    }

    /** The owner opened this service's page or it started: no prompt should remain. */
    fun taken(context: Context, service: String) {
        val app = context.applicationContext
        main.post { board.take(service); cancel(app, service); if (dialog != null && board.get(dialogId ?: "") == null) dismissPopup() }
    }

    /** After the runtime dropped offers (revoked computer): remove their prompts. */
    fun sync(context: Context) {
        val app = context.applicationContext
        main.post {
            val gone = board.retain(SessionOffers.active().map { it.offer.id }.toSet())
            gone.forEach { cancel(app, it.service); if (dialogId == it.id) dismissPopup() }
        }
    }

    fun clearAll(context: Context) {
        val app = context.applicationContext
        main.post { listOf("camera", "screen").forEach { board.take(it); cancel(app, it) }; dismissPopup() }
    }

    private fun expire(context: Context) {
        board.expire(now()).forEach { cancel(context, it.service); if (dialogId == it.id) dismissPopup() }
    }

    private fun notify(context: Context, offer: SessionOffer, computer: String) {
        if (offer.service == "camera") CameraRequests.show(context, offer, computer) else ScreenOfferNotice.show(context, offer, computer)
    }

    private fun cancel(context: Context, service: String) {
        if (service == "camera") CameraRequests.dismiss(context) else ScreenOfferNotice.clear(context)
    }

    fun resumed(activity: Activity) {
        if (dialog != null || AppLock.locked(activity) || activity is PhoneCameraActivity || activity is PhoneScreenActivity) return
        val prompt = board.popupCandidate(now()) ?: return
        if (SessionOffers.peek(prompt.id) != null) popup(activity, prompt)
    }

    fun paused(activity: Activity) {
        if (dialog?.ownerActivity === activity) dismissPopup()
    }

    private fun dismissPopup() {
        val shown = dialog
        dialog = null; dialogId = null
        runCatching { shown?.setOnCancelListener(null); shown?.dismiss() }
    }

    /** Opens the page that verifies the owner and starts; nothing starts here. */
    fun allowIntent(context: Context, service: String, id: String): Intent =
        (if (service == "camera") Intent(context, PhoneCameraActivity::class.java).putExtra(CameraRequests.EXTRA_OFFER, id)
        else Intent(context, PhoneScreenActivity::class.java).putExtra(PhoneScreenActivity.EXTRA_OFFER, id))
            .putExtra(EXTRA_ALLOW, true).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP)

    private fun popup(activity: Activity, prompt: RequestBoard.Prompt) {
        dismissPopup()
        val (title, detail) = RequestBoard.copy(prompt.service, prompt.computer)
        val sheet = Dialog(activity)
        sheet.requestWindowFeature(Window.FEATURE_NO_TITLE)
        sheet.setOwnerActivity(activity)
        val content = LinearLayout(activity).apply {
            orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER_HORIZONTAL
            setPadding(activity.dp(24), activity.dp(24), activity.dp(24), activity.dp(16))
            background = activity.outline(Palette.BG_RAISED, Palette.LINE_STRONG, 28)
        }
        // A single-action screen with its picture: what is asking, then Allow.
        content.addView(ImageView(activity).apply {
            setImageResource(if (prompt.service == "camera") android.R.drawable.ic_menu_camera else com.castle.sefirah.R.drawable.ic_saiph_tile)
            setColorFilter(Palette.ON_TONAL)
            background = GradientDrawable().apply { shape = GradientDrawable.OVAL; setColor(Palette.TONAL); setStroke(activity.dp(1), Palette.TONAL_LINE) }
            setPadding(activity.dp(18), activity.dp(18), activity.dp(18), activity.dp(18))
            contentDescription = null
        }, LinearLayout.LayoutParams(activity.dp(76), activity.dp(76)).apply { bottomMargin = activity.dp(16) })
        content.addView(activity.text(title, UiType.TITLE, bold = true).apply { gravity = Gravity.CENTER })
        content.addView(activity.body(detail).apply { gravity = Gravity.CENTER; setPadding(0, activity.dp(8), 0, activity.dp(20)) })
        val allow = activity.button("Allow", true) {
            dismissPopup()
            if (SessionOffers.peek(prompt.id) != null) activity.startActivity(allowIntent(activity, prompt.service, prompt.id))
        }
        val later = activity.button("Not now") {
            dismissPopup()
            SessionOffers.decline(prompt.id)
            board.close(prompt.id)?.let { cancel(activity.applicationContext, it.service) }
        }
        content.addView(allow, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        content.addView(later, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { topMargin = activity.dp(8) })
        sheet.setContentView(content)
        sheet.window?.apply {
            setBackgroundDrawable(ColorDrawable(Color.TRANSPARENT))
            addFlags(WindowManager.LayoutParams.FLAG_SECURE)
            setLayout(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
            setGravity(Gravity.BOTTOM)
            decorView.setPadding(activity.dp(12), 0, activity.dp(12), activity.dp(16))
        }
        sheet.setOnCancelListener { board.hide(prompt.id); dialog = null; dialogId = null }
        dialog = sheet; dialogId = prompt.id
        runCatching { sheet.show() }.onFailure { dialog = null; dialogId = null }
    }
}
