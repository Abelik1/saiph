package sefirah.network.orion

import kotlinx.serialization.json.*
import java.net.InetAddress
import java.net.URI
import java.net.URLDecoder
import java.time.Instant
import sefirah.network.BuildConfig

/** Numeric addresses only: validation never resolves attacker-supplied DNS names. */
object MeshOrigin {
    const val DEFAULT = BuildConfig.ORION_LEGACY_ORIGIN // Empty in independent builds; legacy owner upgrades only.
    fun isAddress(value: String): Boolean {
        val host = value.removeSurrounding("[", "]")
        if (':' in host) {
            if (!host.matches(Regex("[0-9a-fA-F:]+"))) return false
            val bytes = runCatching { InetAddress.getByName(host).address }.getOrNull() ?: return false
            return bytes.size == 16 && bytes.take(6).map { it.toInt() and 255 } == listOf(0xfd, 0x7a, 0x11, 0x5c, 0xa1, 0xe0)
        }
        val parts = host.split('.')
        if (parts.size != 4 || parts.any { !it.matches(Regex("0|[1-9][0-9]{0,2}")) }) return false
        val bytes = parts.map(String::toInt)
        return bytes.all { it in 0..255 } && bytes[0] == 100 && bytes[1] in 64..127
    }
    fun validate(value: String): String {
        require(value.length in 1..1024 && value.none { it.isWhitespace() || it.code < 32 })
        val uri = URI(value)
        val port = if (uri.port == -1) 8765 else uri.port
        val host = uri.host?.removeSurrounding("[", "]") ?: error("Invalid mesh origin")
        require(uri.scheme == "http" && port in 1024..65535 && uri.rawUserInfo == null &&
            uri.rawQuery == null && uri.rawFragment == null && uri.rawPath in listOf("", "/")) { "Invalid mesh origin" }
        if (DEFAULT.isNotEmpty() && host == BuildConfig.ORION_LEGACY_HOST && port == 8765) return DEFAULT
        require(isAddress(host)) { "Invalid mesh origin" }
        return "http://${if (':' in host) "[${host.lowercase()}]" else host}:$port"
    }
    fun endpoint(address: String, port: Int, path: String): String {
        require(isAddress(address) && port in 1024..65535 && path.startsWith('/') && !path.startsWith("//"))
        return validate("http://${if (':' in address && !address.startsWith('[')) "[$address]" else address}:$port") + path
    }
    fun loginServer(value: String): String {
        require(value.length in 1..1024 && value.none { it.isWhitespace() || it.code < 32 })
        val uri = URI(value)
        require(uri.scheme == "https" && !uri.host.isNullOrBlank() && uri.rawUserInfo == null &&
            uri.rawQuery == null && uri.rawFragment == null && uri.rawPath in listOf("", "/") &&
            (uri.port == -1 || uri.port in 1..65535)) { "Invalid mesh login server" }
        return value.trimEnd('/')
    }
    fun pairing(value: String): Pair<String, String> = Enrollment.link(value).let { it.hub to it.code }
}

/** The existing one-use pairing code is the only enrollment credential. */
data class Enrollment(val hub: String, val code: String, val meshLoginServer: String? = null, val expiresAt: Instant? = null) {
    override fun toString(): String = "Enrollment(private invitation)"
    fun pending(now: Instant): Enrollment = copy(expiresAt = expiresAt ?: now.plusSeconds(600))
    fun expired(now: Instant): Boolean = expiresAt?.let { !it.isAfter(now) } ?: false
    fun privateJson(): String = buildJsonObject {
        put("format", "orion-enrollment"); put("version", 1); put("hub", hub); put("code", code)
        put("expires_at", requireNotNull(expiresAt).toString())
        put("mesh_login_server", meshLoginServer?.let(::JsonPrimitive) ?: JsonNull)
    }.toString()
    companion object {
        fun deviceId(value: String): String = value.also { require(it.matches(Regex("dev_[a-f0-9]{32}"))) }
        private val required = setOf("format", "version", "hub", "code", "expires_at")
        private fun code(value: String): String = value.also { require(it.matches(Regex("[0-9]{8}"))) }
        fun link(value: String): Enrollment {
            require(value.length in 1..4096)
            val uri = URI(value)
            require(uri.scheme == "orion" && uri.host == "pair" && uri.rawUserInfo == null &&
                uri.port == -1 && uri.path.isEmpty() && uri.fragment == null)
            val pairs = (uri.rawQuery ?: "").split('&').map {
                val parts = it.split('=', limit = 2); require(parts.size == 2)
                parts[0] to URLDecoder.decode(parts[1], "UTF-8")
            }
            require(pairs.map { it.first }.toSet().size == pairs.size)
            val args = pairs.toMap()
            require(args.keys.containsAll(setOf("v", "hub", "code")) &&
                args.keys.all { it in setOf("v", "hub", "code", "mesh_login_server") } && args["v"] == "1")
            return Enrollment(MeshOrigin.validate(args.getValue("hub")), code(args.getValue("code")),
                args["mesh_login_server"]?.let(MeshOrigin::loginServer))
        }
        fun file(value: String, now: Instant = Instant.now()): Enrollment {
            require(value.toByteArray(Charsets.UTF_8).size in 1..16384)
            val json = Json.parseToJsonElement(value).jsonObject
            require(json.keys.containsAll(required) && json.keys.all { it in required || it == "mesh_login_server" })
            // All v1 fields are primitive. Reject duplicate/escaped duplicate keys rather than
            // letting different importers disagree about which trusted Hub was selected.
            val keys = Regex("\"(?:[^\"\\\\]|\\\\.)*\"").findAll(value).filter {
                value.substring(it.range.last+1).trimStart().startsWith(':')
            }.map { Json.parseToJsonElement(it.value).jsonPrimitive.content }.toList()
            require(keys.size == json.size && keys.toSet().size == keys.size)
            fun string(key: String) = json.getValue(key).jsonPrimitive.also { require(it.isString) }.content
            require(string("format") == "orion-enrollment")
            require(json.getValue("version").jsonPrimitive.let { !it.isString && it.intOrNull == 1 })
            val expiry = string("expires_at"); require(expiry.endsWith('Z'))
            val expires = Instant.parse(expiry); require(expires.isAfter(now))
            val login = json["mesh_login_server"]?.takeUnless { it == JsonNull }?.jsonPrimitive?.also { require(it.isString) }?.content
            return Enrollment(MeshOrigin.validate(string("hub")), code(string("code")), login?.let(MeshOrigin::loginServer), expires)
        }
    }
}
