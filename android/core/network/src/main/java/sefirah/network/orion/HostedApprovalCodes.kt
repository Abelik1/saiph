// SPDX-License-Identifier: GPL-3.0-only
package sefirah.network.orion

import kotlinx.serialization.json.*
import java.security.SecureRandom
import java.security.Signature
import java.util.Base64
import java.util.UUID

/** Approval codes contain public keys only. A relay response never establishes a pin. */
object HostedApprovalCodes {
    private const val ROOT = "orion-root-v1:"
    private const val REQUEST = "orion-approve-v1:"
    fun inspect(code: String, now: Long = System.currentTimeMillis() / 1000): HostedRoot = HostedSession.guarded {
        check(code.startsWith(ROOT) && code.length <= 2048 && code.all { it.code < 128 })
        val wire = code.removePrefix(ROOT)
        val value = HostedHttpTransport.parse(wire.toByteArray(Charsets.US_ASCII))
        check(value.keys == setOf("data", "signature") && String(HostedEnvelope.canonical(value), Charsets.US_ASCII) == wire)
        val data = value.getValue("data").jsonObject
        check(data.keys == setOf("protocol_version", "deployment_id", "root", "expires_at", "nonce"))
        check(data["protocol_version"] == JsonPrimitive(1))
        check(HostedSession.number(data["expires_at"]) in now + 1..now + 600)
        check(Regex("[A-Za-z0-9_-]{43}").matches(HostedSession.text(data["nonce"])))
        val member = data.getValue("root").jsonObject
        check(member.keys == setOf("id", "signing_key", "encryption_key"))
        val root = HostedRoot(HostedSession.text(data["deployment_id"]), HostedSession.text(member["id"]), HostedSession.text(member["signing_key"]), HostedSession.text(member["encryption_key"]))
        check(UUID.fromString(root.deploymentId).toString() == root.deploymentId && Regex("dev_[a-f0-9]{32}").matches(root.deviceId))
        HostedEnvelope.readPublic(root.encryptionPublic)
        val signature = Base64.getDecoder().decode(HostedSession.text(value["signature"]))
        check(signature.size in 1..80 && Base64.getEncoder().encodeToString(signature) == HostedSession.text(value["signature"]))
        check(Signature.getInstance("SHA256withECDSA").run {
            initVerify(HostedSession.readSigning(root.signingPublic)); update("Orion hosted root approval code v1\u0000".toByteArray(Charsets.US_ASCII) + HostedEnvelope.canonical(data)); verify(signature)
        })
        root
    }
    fun trust(code: String, expectedFingerprint: String): HostedRoot = HostedSession.guarded {
        val root = inspect(code)
        check(expectedFingerprint.replace(" ", "").lowercase() == root.fingerprint())
        root
    }
    fun displayFingerprint(value: String) = value.uppercase().chunked(4).joinToString(" ")
    fun deviceFingerprint(member: JsonObject) = displayFingerprint(HostedSession.digest("Orion hosted device fingerprint v1\u0000".toByteArray(Charsets.US_ASCII) + HostedEnvelope.canonical(member)))
    fun request(session: HostedSession): String = HostedSession.guarded {
        val nonce = ByteArray(32).also { SecureRandom().nextBytes(it) }
        val data = buildJsonObject {
            put("protocol_version", 1); put("deployment_id", session.root.deploymentId); put("root_fingerprint", session.root.fingerprint())
            put("candidate", session.enrollment()); put("expires_at", System.currentTimeMillis() / 1000 + 300)
            put("nonce", Base64.getUrlEncoder().withoutPadding().encodeToString(nonce))
        }
        val signature = Signature.getInstance("SHA256withECDSA").run {
            initSign(session.keys.signingPrivate); update("Orion hosted device approval code v1\u0000".toByteArray(Charsets.US_ASCII) + HostedEnvelope.canonical(data)); sign()
        }
        val result = REQUEST + String(HostedEnvelope.canonical(buildJsonObject {put("data", data); put("signature", Base64.getEncoder().encodeToString(signature))}), Charsets.US_ASCII)
        check(result.length <= 2048)
        result
    }
}

/** Process-local handoff; the default-off gate is checked before invoking this. */
object HostedFeatureBridge {
    @Volatile var publish: ((String, JsonObject) -> Boolean)? = null
    /** Bulk text sync; `delivered` runs only after the root computer's relay accepted it. */
    @Volatile var publishText: ((JsonObject, () -> Unit) -> Boolean)? = null
    fun send(type: String, payload: JsonObject): Boolean = publish?.invoke(type, payload) ?: false
    fun sendText(payload: JsonObject, delivered: () -> Unit): Boolean = publishText?.invoke(payload, delivered) ?: false
}
