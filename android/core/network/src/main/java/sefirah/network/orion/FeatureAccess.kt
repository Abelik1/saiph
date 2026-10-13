package sefirah.network.orion

/** Permission-derived production gates, checked again at enqueue and retry boundaries. */
data class FeatureAccess(val sms: Boolean = false, val calls: Boolean = false,
                         val callControl: Boolean = false, val photos: Boolean = false,
                         val notifications: Boolean = false, val clipboard: Boolean = false,
                         val contacts: Boolean = false, val callLog: Boolean = false,
                         val callDial: Boolean = false, val ringer: Boolean = false) {
    fun allowsPublication(type: String): Boolean = when {
        type.startsWith("sms.") -> sms
        type == "call.state" -> calls
        type.startsWith("photos.") || type == "photo.original" -> photos
        type.startsWith("notification.") -> notifications
        type == "media.state" -> notifications // Media sessions are read through notification access.
        type == "contacts.results" -> contacts
        type == "calls.log" -> callLog
        type == "clipboard" -> clipboard
        else -> true // Explicit SAF file sharing has independent consent.
    }
    fun capabilities(): List<String> = buildList {
        add("files")
        if (sms) add("sms")
        if (calls) add("calls")
        if (calls && callControl) add("call-control")
        if (photos) add("photos")
        if (notifications) { add("notifications"); add("media") }
        if (contacts) add("contacts")
        if (callLog) add("call-log")
        if (callDial) add("call-dial")
        if (ringer) add("ringer")
    }
}
