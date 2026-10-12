package sefirah.network.orion

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import java.time.Instant

class EnrollmentTest {
    @Test fun pairingAcceptsTheExistingHubDeviceIdFormat() {
        val id="dev_0123456789abcdef0123456789abcdef"
        assertEquals(id, Enrollment.deviceId(id))
        listOf("01234567-89ab-cdef-0123-456789abcdef", "dev_bad", "../device").forEach {
            assertTrue(runCatching { Enrollment.deviceId(it) }.isFailure)
        }
    }
    private val now = Instant.parse("2026-10-08T12:00:00Z")
    private fun file(hub: String = "http://100.100.10.2:8765", login: JsonElement? = JsonNull) = buildJsonObject {
        put("format", "orion-enrollment"); put("version", 1); put("hub", hub); put("code", "12345678")
        put("expires_at", "2026-10-08T12:10:00Z"); login?.let { put("mesh_login_server", it) }
    }.toString()
    @Test fun friendOriginAndCustomPortSurviveValidationAndRepeatedMigrationNormalization() {
        val invite = Enrollment.file(file("http://100.100.10.2:12345"), now)
        assertEquals("http://100.100.10.2:12345", invite.hub)
        repeat(20) { assertEquals(invite.hub, MeshOrigin.validate(invite.hub)) }
        assertEquals("http://100.100.10.2:8765", MeshOrigin.validate("http://100.100.10.2/"))
        if (MeshOrigin.DEFAULT.isEmpty()) assertTrue(runCatching { MeshOrigin.validate("http://legacy.example.invalid:8765") }.isFailure)
        else assertEquals(MeshOrigin.DEFAULT, MeshOrigin.validate("http://legacy.example.invalid:8765"))
    }
    @Test fun literalMeshBoundaryAndIpv6GatesNeverAcceptDnsPublicOrLanHosts() {
        listOf("100.64.0.0", "100.127.255.255", "fd7a:115c:a1e0::1", "fd7a:115c:a1e0:ffff:ffff:ffff:ffff:ffff").forEach {
            assertTrue(it, MeshOrigin.isAddress(it))
        }
        listOf("100.63.255.255", "100.128.0.0", "100.64.0.256", "100.064.0.1", "100.64.1", "127.0.0.1", "192.168.1.2",
            "legacy.example.invalid", "100.64.0.2.attacker.example", "fd7a:115c:a1e1::1", "::ffff:100.64.0.2", "fd7a:115c:a1e0::1%wlan0").forEach {
            assertFalse(it, MeshOrigin.isAddress(it))
        }
        assertEquals("http://[fd7a:115c:a1e0::1]:8765", MeshOrigin.validate("http://[fd7a:115c:a1e0::1]:8765"))
    }
    @Test fun originCannotRedirectSigningKeyByAuthorityOrPathInjection() {
        listOf("https://100.64.0.2:8765", "http://100.64.0.2:80", "http://100.64.0.2:65536", "http://100.64.0.2:8765/v1",
            "http://100.64.0.2:8765?next=evil", "http://100.64.0.2:8765#evil", "http://secret@100.64.0.2:8765",
            "http://100.64.0.2:8765@evil.example:8765", "http://100.64.0.2:8765\n", "http://100.64.0.2.:8765").forEach {
            assertTrue(it, runCatching { MeshOrigin.validate(it) }.isFailure)
        }
    }
    @Test fun existingQrAndOptionalControllerQrRemainCompatible() {
        val qr = "orion://pair?v=1&hub=http%3A%2F%2F100.100.10.2%3A8765&code=12345678"
        assertEquals("http://100.100.10.2:8765" to "12345678", MeshOrigin.pairing(qr))
        assertNull(Enrollment.link(qr).meshLoginServer)
        assertEquals("https://mesh.example.test", Enrollment.link(qr+"&mesh_login_server=https%3A%2F%2Fmesh.example.test").meshLoginServer)
        listOf(qr+"&code=87654321", qr+"&mesh_login_server=", qr+"&mesh_login_server=http%3A%2F%2Fmesh.example.test", qr+"&authkey=private",
            qr+"&mesh_login_server=https%3A%2F%2Fmesh.example.test&mesh_login_server=https%3A%2F%2Fevil.example").forEach {
            assertTrue(runCatching { Enrollment.link(it) }.isFailure)
        }
    }
    @Test fun optionalControllerHasNoCredentialsQueriesPathsOrNonHttps() {
        assertEquals("https://mesh.example.test:8443", MeshOrigin.loginServer("https://mesh.example.test:8443/"))
        listOf("http://mesh.example.test", "https://user:secret@mesh.example.test", "https://mesh.example.test/path", "https://mesh.example.test?authkey=secret", "https://mesh.example.test#secret").forEach {
            assertTrue(runCatching { MeshOrigin.loginServer(it) }.isFailure)
        }
    }
    @Test fun independentFileAbsentOrNullControllerNeverDefaultsToOwnerController() {
        assertNull(Enrollment.file(file(login=null), now).meshLoginServer)
        assertNull(Enrollment.file(file(), now).meshLoginServer)
        assertEquals("https://mesh.example.test", Enrollment.file(file(login=JsonPrimitive("https://mesh.example.test")), now).meshLoginServer)
    }
    @Test fun privatePendingRoundTripKeepsExpiryAndExpiresWithoutFurtherRequests() {
        val invite = Enrollment.link("orion://pair?v=1&hub=http%3A%2F%2F100.100.10.2%3A8765&code=12345678").pending(now)
        assertFalse(invite.expired(now.plusSeconds(599)))
        assertTrue(invite.expired(now.plusSeconds(600)))
        assertEquals(invite, Enrollment.file(invite.privateJson(), now))
        assertTrue(runCatching { Enrollment.file(invite.privateJson(), now.plusSeconds(600)) }.isFailure)
    }
    @Test fun malformedExpiredOversizedOrAmbiguousFileDoesNotBecomeAnInvitation() {
        listOf(file().replace("12345678", "1234"), file().replace("\"version\":1", "\"version\":\"1\""),
            file().replace("12:10:00Z", "11:59:59Z"), file().replace("12:10:00Z", "12:10:00+00:00"),
            file().replace("\"hub\":", "\"hub\":\"http://100.64.0.2:8765\",\"hub\":"),
            file().dropLast(1)+",\"authkey\":\"secret\"}", file().dropLast(1)+",\"h\\u0075b\":\"http://100.64.0.2:8765\"}",
            " ".repeat(16385)+file()).forEach {
            assertTrue(runCatching { Enrollment.file(it, now) }.isFailure)
        }
    }
    @Test fun directTransferEndpointUsesSameMeshGateAndBracketsIpv6() {
        val path="/v1/peer/owner/blobs/id"
        assertEquals("http://[fd7a:115c:a1e0::1]:8767$path", MeshOrigin.endpoint("fd7a:115c:a1e0::1",8767,path))
        assertTrue(runCatching { MeshOrigin.endpoint("attacker.example",8767,path) }.isFailure)
        assertTrue(runCatching { MeshOrigin.endpoint("100.64.0.2",80,path) }.isFailure)
        assertTrue(runCatching { MeshOrigin.endpoint("100.64.0.2",8767,"//attacker.example") }.isFailure)
    }
}
