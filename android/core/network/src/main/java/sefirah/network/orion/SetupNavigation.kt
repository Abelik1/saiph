package sefirah.network.orion

/** Setup completion and deferral have different meanings across Activity recreation. */
object SetupNavigation {
    fun resume(current: String, paired: Boolean, complete: Boolean, deferred: Boolean,
               requestSetup: Boolean = false, requestSettings: Boolean = false): String = when {
        !paired -> "pair"
        requestSetup -> "setup"
        requestSettings -> "settings"
        !complete && !deferred -> "setup"
        current in setOf("setup", "settings", "advanced") -> current
        else -> "home"
    }
    fun back(current: String): String? = when (current) {
        "setup", "settings" -> "home"
        "advanced" -> "settings"
        else -> null
    }
    fun offersBack(current: String, paired: Boolean) = paired && current != "home"
    fun notificationOpensSetup(complete: Boolean, deferred: Boolean) = !complete && !deferred
}
