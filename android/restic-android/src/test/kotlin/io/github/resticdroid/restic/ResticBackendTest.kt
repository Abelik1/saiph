package io.github.resticdroid.restic

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ResticBackendTest {
    @Test
    fun `b2 uri gets its scheme prefixed exactly once`() {
        assertEquals("b2:my-bucket:phone", ResticBackend.B2.uriFor("my-bucket:phone"))
        assertEquals("b2:my-bucket:phone", ResticBackend.B2.uriFor("b2:my-bucket:phone"))
        assertEquals("b2:my-bucket:phone", ResticBackend.B2.uriFor("  my-bucket:phone  "))
    }

    @Test
    fun `local paths are passed through unchanged`() {
        assertEquals("/storage/emulated/0/Backups", ResticBackend.LOCAL.uriFor("/storage/emulated/0/Backups"))
    }

    @Test
    fun `backend is detected from an existing uri`() {
        assertEquals(ResticBackend.B2, ResticBackend.detect("b2:bucket:path"))
        assertEquals(ResticBackend.S3, ResticBackend.detect("s3:s3.amazonaws.com/b"))
        assertEquals(ResticBackend.LOCAL, ResticBackend.detect("/storage/emulated/0/x"))
    }

    @Test
    fun `b2 asks for exactly the two variables restic reads`() {
        val keys = ResticBackend.B2.credentials.map { it.key }
        assertEquals(listOf("B2_ACCOUNT_ID", "B2_ACCOUNT_KEY"), keys)
        assertTrue(ResticBackend.B2.credentials.single { it.key == "B2_ACCOUNT_KEY" }.secret)
    }

    @Test
    fun `no backend is offered that needs a binary Android does not have`() {
        val ids = ResticBackend.entries.map { it.id }
        assertTrue(!ids.contains("sftp"))
        assertTrue(!ids.contains("rclone"))
    }

    @Test
    fun `each credential declares how it reaches restic`() {
        assertEquals(
            listOf(Delivery.UrlUser, Delivery.UrlPassword),
            ResticBackend.REST.credentials.map { it.delivery },
        )
        assertEquals(
            Delivery.PrivateFile,
            ResticBackend.GS.credentials.single { it.key == "GOOGLE_APPLICATION_CREDENTIALS" }.delivery,
        )
        assertTrue(ResticBackend.B2.credentials.all { it.delivery == Delivery.Environment })
        assertTrue(ResticBackend.S3.credentials.all { it.delivery == Delivery.Environment })
    }

    @Test
    fun `every backend has a stable id and no duplicates`() {
        val ids = ResticBackend.entries.map { it.id }
        assertEquals(ids.size, ids.toSet().size)
        ids.forEach { assertTrue(it.isNotBlank()) }
    }

    @Test
    fun `repository hides its password when printed`() {
        val repo = ResticRepository("b2:b:p", "hunter2", mapOf("B2_ACCOUNT_KEY" to "secret"))
        val printed = repo.toString()
        assertTrue(!printed.contains("hunter2"))
        assertTrue(!printed.contains("secret"))
        assertTrue(printed.contains("B2_ACCOUNT_KEY"))
    }
}
