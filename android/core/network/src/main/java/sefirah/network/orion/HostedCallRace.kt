// SPDX-License-Identifier: GPL-3.0-only
package sefirah.network.orion

import sefirah.domain.model.CallState

/**
 * First come, first served call handling for several Saiph Hosted computers.
 *
 * The phone carries out the first answer or decline it receives for a ringing
 * call and refuses every later one for the same call, naming the computer that
 * won. A dial is refused while the phone is on a call or is already placing one.
 * Pure state; the bridge supplies Android's call state and performs the action.
 */
class HostedCallRace(private val clock: () -> Long = System::currentTimeMillis) {
    sealed interface Outcome
    data object Won : Outcome
    /** [reason]: handled, not_ringing, in_call or dialing; [handled]/[by] name the winner. */
    data class Refused(val reason: String, val handled: String = "", val by: String = "") : Outcome

    private var ringing = false
    private var winner: Pair<String, Boolean>? = null
    private var declinedAt = Long.MIN_VALUE
    private var dialingUntil = 0L
    private var last: Any? = null

    /** Called for each published call state; copies of one event for several computers count once. */
    @Synchronized fun observe(event: Any, state: CallState) {
        if (event === last) return
        last = event
        when (state) {
            CallState.Ringing -> { ringing = true; winner = null }
            CallState.InProgress -> ringing = false
            CallState.MissedCall, CallState.Ended -> { ringing = false; dialingUntil = 0 }
        }
    }

    /** A call declined from a computer ends as "ended", not as a missed call. */
    @Synchronized fun published(state: CallState): CallState =
        if (state == CallState.MissedCall && winner?.second == false && clock() - declinedAt in 0..15_000) CallState.Ended else state

    /** [phoneRinging] is Android's own view; both must agree the call still rings. */
    @Synchronized fun claimCall(by: String, answer: Boolean, phoneRinging: Boolean): Outcome {
        winner?.let { (label, answered) -> return Refused("handled", if (answered) "answer" else "reject", label) }
        if (!ringing || !phoneRinging) return Refused("not_ringing")
        winner = by to answer
        ringing = false
        if (!answer) declinedAt = clock()
        return Won
    }

    /** [phoneBusy]: Android reports a call off-hook or ringing. Telecom needs a few seconds to show a placed call. */
    @Synchronized fun claimDial(phoneBusy: Boolean): Outcome {
        if (phoneBusy) return Refused("in_call")
        if (clock() < dialingUntil) return Refused("dialing")
        dialingUntil = clock() + 10_000
        return Won
    }

    companion object {
        /** One phone, one race: shared by the network manager and the hosted bridge. */
        val shared = HostedCallRace()
    }
}
