package sefirah.network.orion

/** Permission-derived production gates, checked again at enqueue and retry boundaries. */
data class FeatureAccess(val sms: Boolean = false, val calls: Boolean = false,
                         val callControl: Boolean = false, val photos: Boolean = false,
                         val notifications: Boolean = false, val clipboard: Boolean = false) {
    fun allowsPublication(type: String): Boolean = when {
        type.startsWith("sms.") -> sms
        type == "call.state" -> calls
        type.startsWith("photos.") || type == "photo.original" -> photos
        type.startsWith("notification.") -> notifications
        type == "clipboard" -> clipboard
        else -> true // Explicit SAF file sharing has independent consent.
    }
    fun capabilities(): List<String> = buildList {
        add("files")
        if (sms) add("sms")
        if (calls) add("calls")
        if (calls && callControl) add("call-control")
        if (photos) add("photos")
        if (notifications) add("notifications")
    }
}
