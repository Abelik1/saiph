// SPDX-License-Identifier: GPL-3.0-only
package sefirah.network.orion

import android.content.Context
import kotlinx.serialization.json.JsonObject

/**
 * The self-hosted Hub transport for the shared phone status and quick actions
 * (Saiph Cloud's is in the app's HostedRuntime). One `phone.status` event goes
 * to the Hub, which fans it out to every paired computer; a current Hub checks
 * its shape and keeps the latest one for computers that reconnect, an older Hub
 * relays it unchecked and the desktop checks it.
 *
 * Wi-Fi, Bluetooth and signal therefore reach Hub computers too. Sync over
 * mobile data is a Cloud setting, so a Hub phone always reports it on and never
 * paused. The wallpaper goes only to the computer that asked, never stored on the Hub.
 */
class LinkPhoneStatus(private val context: Context, private val link: OrionLink) {
    private val publisher = PhoneStatusPublisher()

    /** A new Hub connection: computers that missed updates get the status again. */
    fun connected() { publisher.reset(); sync() }

    /** Called on the service's loop and after any change it notices; [PhoneStatusFrames.due] limits the rate. */
    fun sync(force: Boolean = false) {
        if (link.status.value != "Online") return
        val current = PhoneQuickControls.current(context, PhoneTransport.LINK, mobileData = true, paused = false)
        publisher.sync(setOf(PhoneStatusPublisher.BROADCAST), current, force, System.currentTimeMillis()) {
            // Older desktops ignore phone.signal; older Hubs relay it unchecked.
            link.publish(PhoneStatusFrames.STATUS, PhoneStatusFrames.body(current)) &&
                link.publish(PhoneStatusFrames.SIGNAL, PhoneStatusFrames.signalBody(current))
        }
    }

    fun invalidate() = publisher.invalidate()

    /**
     * A quick action relayed by the Hub: Refresh, Do Not Disturb, the hotspot or the wallpaper.
     * Runs only when this phone lists the control now, at most once per event.
     * Returns true when the event was one of them.
     */
    fun receive(type: String, body: JsonObject, source: String, claim: () -> Boolean): Boolean {
        if (type !in PhoneStatusFrames.LINK_COMMANDS) return false
        val command = PhoneStatusFrames.linkCommand(type, body, PhoneQuickControls.controls(context, PhoneTransport.LINK)) ?: return true
        if (!claim()) return true
        when (command) {
            PhoneControlCommand.Status -> publisher.refresh(source, PhoneStatusPublisher.BROADCAST, System.currentTimeMillis())
            PhoneControlCommand.Wallpaper -> runCatching {
                link.publish(PhoneStatusFrames.WALLPAPER, PhoneStatusFrames.wallpaperBody(PhoneQuickControls.wallpaper(context)), source)
            }
            else -> runCatching { PhoneQuickControls.apply(context, command) }
        }
        sync()
        return true
    }
}
