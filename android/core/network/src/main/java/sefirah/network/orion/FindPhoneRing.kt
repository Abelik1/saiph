// SPDX-License-Identifier: GPL-3.0-only
package sefirah.network.orion

/**
 * Find-my-phone ringing as plain state, so its rules are testable without Android:
 * one ring at a time, always time-bounded, stopped by the owner from any place, and
 * never silently left running because a notification was swiped away.
 */
class FindPhoneRing(private val millis: Long = OrionRing.SECONDS * 1000) {
    sealed interface State {
        data object Idle : State
        /** [from] is the asking computer's name when known; [until] is when ringing stops by itself. */
        data class Ringing(val from: String?, val until: Long) : State
    }

    var state: State = State.Idle
        private set

    /** A new request rings for the full time again, and names the newest computer. */
    fun start(from: String?, now: Long): State.Ringing =
        State.Ringing(from?.trim()?.takeIf { it.isNotEmpty() }?.take(80), now + millis).also { state = it }

    /** Stop from the screen, the notification, a volume or power press. True if it was ringing. */
    fun stop(): Boolean = (state is State.Ringing).also { state = State.Idle }

    /** Called when the time is up. True if this ended the ring. */
    fun expire(now: Long): Boolean {
        val current = state as? State.Ringing ?: return false
        if (now < current.until) return false
        state = State.Idle; return true
    }

    /**
     * The ringing notification was dismissed. Dismissing is not stopping: while the ring
     * lasts, the notification comes back, so Stop is always one tap away. True means post it again.
     */
    fun dismissed(now: Long): Boolean {
        expire(now)
        return state is State.Ringing
    }

    /** Whole seconds left, for "Stops by itself in …"; 0 when idle. */
    fun remaining(now: Long): Long = (state as? State.Ringing)?.let { ((it.until - now + 999) / 1000).coerceAtLeast(0) } ?: 0
}
