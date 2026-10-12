package sefirah.network.orion

import kotlinx.serialization.json.*
import java.security.AlgorithmParameters
import java.security.KeyFactory
import java.security.MessageDigest
import java.security.PublicKey
import java.security.Signature
import java.security.interfaces.ECPublicKey
import java.security.spec.ECGenParameterSpec
import java.security.spec.ECParameterSpec
import java.security.spec.X509EncodedKeySpec
import java.util.Base64
import java.util.UUID

class HostedSessionException : IllegalStateException("Cannot verify hosted device trust or encrypted delivery.")

/** Explicit trust anchor obtained independently of the hosted mailbox/account. */
data class HostedRoot(val deploymentId: String, val deviceId: String, val signingPublic: String, val encryptionPublic: String) {
    fun member() = buildJsonObject { put("id", deviceId); put("signing_key", signingPublic); put("encryption_key", encryptionPublic) }
    fun fingerprint(): String = HostedSession.digest("Orion hosted root fingerprint v1\u0000".toByteArray(Charsets.US_ASCII) +
        HostedEnvelope.canonical(buildJsonObject { put("deployment_id", deploymentId); put("root", member()) }))
}

/** Root-pinned, fail-closed authority for an isolated hosted client adapter. */
class HostedSession(
    val root: HostedRoot,
    val deviceId: String,
    internal val keys: HostedRecipientMaterial,
    private val store: HostedTrustStore,
    private val clock: () -> Long = { System.currentTimeMillis() / 1000 },
) {
    private var roster: JsonObject? = null
    private var head: HostedCheckpoint? = null

    companion object {
        private val rosterDomain = "Orion hosted roster v1\u0000".toByteArray(Charsets.US_ASCII)
        private val enrollmentDomain = "Orion hosted enrollment v1\u0000".toByteArray(Charsets.US_ASCII)
        internal fun digest(bytes: ByteArray): String = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
        internal inline fun <T> guarded(action: () -> T): T = try { action() } catch (_: Exception) { throw HostedSessionException() }
        internal fun text(value: JsonElement?): String {
            check(value is JsonPrimitive && value.isString)
            return value.content
        }
        internal fun number(value: JsonElement?): Long {
            check(value is JsonPrimitive && !value.isString && Regex("0|[1-9][0-9]*").matches(value.content))
            return value.content.toLong()
        }
        internal fun publicSigning(key: PublicKey): String = Base64.getEncoder().encodeToString(key.encoded)
        internal fun readSigning(encoded: String): PublicKey {
            check(encoded.length <= 344)
            val raw = Base64.getDecoder().decode(encoded)
            check(Base64.getEncoder().encodeToString(raw) == encoded)
            val key = KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(raw))
            check(key is ECPublicKey && publicSigning(key) == encoded)
            val expected = AlgorithmParameters.getInstance("EC").apply { init(ECGenParameterSpec("secp256r1")) }.getParameterSpec(ECParameterSpec::class.java)
            check(key.params.curve == expected.curve && key.params.generator == expected.generator && key.params.order == expected.order)
            return key
        }
        private fun verify(key: PublicKey, encoded: String, data: ByteArray) {
            check(encoded.isNotEmpty() && encoded.length <= 108)
            val raw = Base64.getDecoder().decode(encoded)
            check(raw.size <= 80 && Base64.getEncoder().encodeToString(raw) == encoded)
            check(Signature.getInstance("SHA256withECDSA").run { initVerify(key); update(data); verify(raw) })
        }
    }

    init {
        guarded {
            check(UUID.fromString(root.deploymentId).toString() == root.deploymentId && Regex("dev_[a-f0-9]{32}").matches(deviceId))
            validateMember(root.member(), 1, 1)
            val signing = publicSigning(keys.signingPublic)
            readSigning(signing)
            val recipient = HostedEnvelope.exportPublic(keys.recipient)
            store.bind(buildJsonObject {
                put("deployment_id", root.deploymentId); put("device_id", deviceId)
                put("root", root.member()); put("signing_key", signing); put("encryption_key", recipient)
            })
        }
    }

    private fun validateMember(member: JsonObject, version: Long, expiry: Long) {
        check(member.keys == setOf("id", "signing_key", "encryption_key"))
        val id = text(member["id"])
        HostedEnvelope.validateHeader(buildJsonObject {
            put("protocol_version", 1); put("deployment_id", root.deploymentId); put("roster_version", version)
            put("roster_hash", "0".repeat(64)); put("id", UUID.randomUUID().toString())
            put("source", id); put("target", id); put("expires_at", expiry)
        })
        readSigning(text(member["signing_key"]))
        HostedEnvelope.readPublic(text(member["encryption_key"]))
    }

    @Synchronized fun invalidate() { roster = null; head = null }

    private fun detached(value: JsonObject): JsonObject =
        Json.parseToJsonElement(String(HostedEnvelope.canonical(value), Charsets.US_ASCII)).jsonObject

    private fun members(candidate: JsonObject): Map<String, JsonObject> = candidate.getValue("members").jsonArray.associate {
        text(it.jsonObject["id"]) to it.jsonObject
    }

    private fun verifyRoster(entry: JsonObject, version: Long, previousHash: String?): JsonObject {
        check(version in 1..2_147_483_647L && entry.keys == setOf("roster", "signature"))
        val candidate = entry.getValue("roster").jsonObject
        check(candidate.keys == setOf("deployment_id", "version", "previous_hash", "expires_at", "members"))
        check(text(candidate["deployment_id"]) == root.deploymentId && number(candidate["version"]) == version)
        check(if (version == 1L) candidate["previous_hash"] == JsonNull else previousHash != null &&
            Regex("[a-f0-9]{64}").matches(previousHash) && text(candidate["previous_hash"]) == previousHash)
        val expiry = number(candidate["expires_at"])
        check(expiry in 1..253_402_300_799L)
        val list = candidate.getValue("members").jsonArray
        check(list.size in 1..32)
        val ids = list.map {
            validateMember(it.jsonObject, version, expiry)
            text(it.jsonObject["id"])
        }
        check(ids == ids.sorted() && ids.toSet().size == ids.size)
        check(members(candidate)[root.deviceId] == root.member())
        if (version == 1L) check(list.size == 1)
        verify(readSigning(root.signingPublic), text(entry["signature"]), rosterDomain + HostedEnvelope.canonical(candidate))
        return candidate
    }

    private fun verifyTransition(before: Map<String, JsonObject>, after: Map<String, JsonObject>, used: Set<String>) {
        for ((id, member) in after) if (id in before) check(before[id] == member) else check(id !in used)
    }

    private fun retainedAnchor(snapshot: HostedTrustSnapshot): JsonObject? {
        if (snapshot.checkpoint.version == 0L) {
            check(snapshot.checkpoint.digest.isEmpty() && snapshot.signedAnchor == null && snapshot.usedDeviceIds.isEmpty())
            return null
        }
        val anchor = snapshot.signedAnchor ?: throw HostedSessionException()
        val candidate = anchor.getValue("roster").jsonObject
        val previous = if (snapshot.checkpoint.version == 1L) null else text(candidate["previous_hash"])
        val verified = verifyRoster(anchor, snapshot.checkpoint.version, previous)
        check(digest(HostedEnvelope.canonical(verified)) == snapshot.checkpoint.digest &&
            snapshot.usedDeviceIds.containsAll(members(verified).keys) &&
            snapshot.usedDeviceIds.all { Regex("dev_[a-f0-9]{32}").matches(it) })
        return verified
    }

    private fun activate(snapshot: HostedTrustSnapshot) {
        val accepted = retainedAnchor(snapshot) ?: throw HostedSessionException()
        val now = clock()
        check(number(accepted["expires_at"]) in (now + 1)..(now + 86_400))
        val own = members(accepted)[deviceId] ?: throw HostedSessionException()
        check(text(own["signing_key"]) == publicSigning(keys.signingPublic) &&
            text(own["encryption_key"]) == HostedEnvelope.exportPublic(keys.recipient))
        check(store.snapshot() == snapshot)
        roster = detached(accepted)
        head = snapshot.checkpoint
    }

    /** A verified local checkpoint, never an operator-provided head hint. */
    @Synchronized fun pagingCheckpoint(): HostedCheckpoint = guarded {
        val snapshot = store.snapshot()
        retainedAnchor(snapshot)
        snapshot.checkpoint
    }

    /** Persist at most 16 verified successors; historical pages never authorize content. */
    @Synchronized fun acceptPage(chain: JsonArray, final: Boolean) {
        invalidate()
        try {
            check(chain.size <= 16 && (chain.isNotEmpty() || final))
            val entries = chain.toList().map { detached(it.jsonObject) }
            check(entries.size <= 16 && (entries.isNotEmpty() || final))
            val old = store.snapshot()
            var previous = retainedAnchor(old)
            var previousHash = old.checkpoint.digest.ifEmpty { null }
            var version = old.checkpoint.version
            val used = old.usedDeviceIds.toMutableSet()
            var latest = old.signedAnchor
            for (entry in entries) {
                val candidate = verifyRoster(entry, ++version, previousHash)
                val nextMembers = members(candidate)
                verifyTransition(previous?.let(::members) ?: emptyMap(), nextMembers, used)
                used += nextMembers.keys
                previousHash = digest(HostedEnvelope.canonical(candidate))
                previous = candidate
                latest = detached(entry)
            }
            val next = HostedTrustSnapshot(HostedCheckpoint(version, previousHash ?: ""), latest, used.toSet())
            if (entries.isNotEmpty()) store.advance(old, next)
            // Commit even an expired or revoked final anchor before rejecting
            // its content authority, so older signed history cannot restore it.
            if (final) activate(next)
        } catch (_: Exception) {
            invalidate()
            throw HostedSessionException()
        }
    }

    /** Full-genesis compatibility and legacy checkpoint migration only, <=128 entries. */
    @Synchronized fun acceptChain(chain: JsonArray) {
        invalidate()
        try {
            check(chain.size in 1..128)
            val entries = chain.toList().map { detached(it.jsonObject) }
            check(entries.size in 1..128)
            val old = store.snapshot()
            var previousHash: String? = null
            var previousMembers = emptyMap<String, JsonObject>()
            val used = mutableSetOf<String>()
            val hashes = mutableListOf<String>()
            var latest: JsonObject? = null
            for ((index, entry) in entries.withIndex()) {
                val candidate = verifyRoster(entry, index + 1L, previousHash)
                val members = members(candidate)
                verifyTransition(previousMembers, members, used)
                previousHash = digest(HostedEnvelope.canonical(candidate))
                hashes += previousHash
                previousMembers = members
                used += members.keys
                latest = detached(entry)
            }
            check(old.checkpoint.version in 0..entries.size.toLong() &&
                (old.checkpoint.version == 0L || hashes[old.checkpoint.version.toInt() - 1] == old.checkpoint.digest))
            if (old.signedAnchor != null || old.checkpoint.version == 0L) retainedAnchor(old)
            check(used.containsAll(old.usedDeviceIds))
            val next = HostedTrustSnapshot(HostedCheckpoint(entries.size.toLong(), hashes.last()), latest, used.toSet())
            store.advance(old, next)
            activate(next)
        } catch (_: Exception) {
            invalidate()
            throw HostedSessionException()
        }
    }

    @Synchronized fun currentMembers(): Map<String, JsonObject> = guarded {
        val current = roster ?: throw HostedSessionException()
        val checkpoint = head ?: throw HostedSessionException()
        check(number(current["expires_at"]) > clock() && digest(HostedEnvelope.canonical(current)) == checkpoint.digest && store.checkpoint() == checkpoint)
        val detached = Json.parseToJsonElement(String(HostedEnvelope.canonical(current), Charsets.US_ASCII)).jsonObject
        detached.getValue("members").jsonArray.associate { text(it.jsonObject["id"]) to it.jsonObject }
    }

    @Synchronized fun encrypt(target: String, payload: JsonObject, ttlSeconds: Int = 60): JsonObject = guarded {
        val members = currentMembers()
        check(target != deviceId && target in members && ttlSeconds in 1..300)
        val checkpoint = head ?: throw HostedSessionException()
        val header = buildJsonObject {
            put("protocol_version", 1); put("deployment_id", root.deploymentId); put("roster_version", checkpoint.version)
            put("roster_hash", checkpoint.digest); put("id", UUID.randomUUID().toString()); put("source", deviceId)
            put("target", target); put("expires_at", clock() + ttlSeconds)
        }
        buildJsonObject {
            put("header", header)
            put("ciphertext", HostedEnvelope.seal(text(members.getValue(target)["encryption_key"]), keys.signingPrivate, header, payload))
        }
    }

    /** Pure verification/decryption; does not execute or durably claim an effect. */
    @Synchronized fun authenticate(envelope: JsonObject): JsonObject = guarded {
        val members = currentMembers()
        check(envelope.keys == setOf("header", "ciphertext"))
        val header = envelope.getValue("header").jsonObject
        HostedEnvelope.validateHeader(header)
        val checkpoint = head ?: throw HostedSessionException()
        val source = text(header["source"])
        check(text(header["deployment_id"]) == root.deploymentId && number(header["roster_version"]) == checkpoint.version &&
            text(header["roster_hash"]) == checkpoint.digest && source in members && source != deviceId &&
            text(header["target"]) == deviceId && number(header["expires_at"]) in (clock() + 1)..(clock() + 300))
        HostedEnvelope.openEnvelope(keys.recipient, readSigning(text(members.getValue(source)["signing_key"])), header, text(envelope["ciphertext"]))
    }

    /** Replay identity and ciphertext commit together before remote ACK. */
    @Synchronized fun receiveIntoEncryptedInbox(envelope: JsonObject): HostedInboxReceipt = guarded {
        val detached = Json.parseToJsonElement(String(HostedEnvelope.canonical(envelope), Charsets.US_ASCII)).jsonObject
        authenticate(detached)
        store.acceptIncoming(detached, head ?: throw HostedSessionException(), clock())
    }

    fun pendingIncoming(): List<JsonObject> = guarded { store.pendingIncoming(clock()) }

    fun completeIncoming(id: String) = guarded { store.completeIncoming(id) }

    fun enrollment(): JsonObject = guarded {
        val candidate = buildJsonObject {
            put("deployment_id", root.deploymentId)
            put("device", buildJsonObject { put("id", deviceId); put("signing_key", publicSigning(keys.signingPublic)); put("encryption_key", HostedEnvelope.exportPublic(keys.recipient)) })
        }
        val proof = Signature.getInstance("SHA256withECDSA").run {
            initSign(keys.signingPrivate); update(enrollmentDomain + HostedEnvelope.canonical(candidate)); sign()
        }
        JsonObject(candidate + ("proof" to JsonPrimitive(Base64.getEncoder().encodeToString(proof))))
    }
}
