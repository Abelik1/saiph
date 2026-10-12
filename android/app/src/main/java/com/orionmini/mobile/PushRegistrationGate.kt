package com.orionmini.mobile

/** Bound optional push registration independently from normal mesh inbox refreshes. */
internal class PushRegistrationGate(private val retryMillis: Long = 300_000L) {
    private var registered = false
    private var inFlight = false
    private var retryAt = 0L

    @Synchronized fun begin(nowMillis: Long): Boolean {
        if (registered || inFlight || nowMillis < retryAt) return false
        inFlight = true
        retryAt = nowMillis + retryMillis
        return true
    }

    @Synchronized fun finished(success: Boolean) {
        registered = success
        inFlight = false
    }
}
