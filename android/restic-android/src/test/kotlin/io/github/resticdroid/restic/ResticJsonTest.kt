package io.github.resticdroid.restic

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ResticJsonTest {
    @Test
    fun `parses a backup status line`() {
        val line = """
            {"message_type":"status","seconds_elapsed":12,"seconds_remaining":48,
             "percent_done":0.25,"total_files":1200,"files_done":300,
             "total_bytes":10485760,"bytes_done":2621440,
             "current_files":["/storage/emulated/0/DCIM/a.jpg"]}
        """.trimIndent().replace("\n", "")

        val event = ResticJson.parseLine(line) as ResticEvent.Progress
        assertEquals(0.25, event.percentDone, 0.0001)
        assertEquals(1200L, event.totalFiles)
        assertEquals(300L, event.filesDone)
        assertEquals(2621440L, event.bytesDone)
        assertEquals(48L, event.secondsRemaining)
        assertEquals(listOf("/storage/emulated/0/DCIM/a.jpg"), event.currentFiles)
    }

    @Test
    fun `parses a summary line`() {
        val line = """{"message_type":"summary","files_new":10,"files_changed":2,
            |"files_unmodified":900,"dirs_new":3,"dirs_changed":1,"dirs_unmodified":40,
            |"data_added":123456,"data_added_packed":100000,"total_files_processed":912,
            |"total_bytes_processed":98765432,"total_duration":42.5,
            |"snapshot_id":"3fd9a1c2b8"}""".trimMargin().replace("\n", "")

        val event = ResticJson.parseLine(line) as ResticEvent.Summary
        assertEquals("3fd9a1c2b8", event.snapshotId)
        assertEquals(10L, event.filesNew)
        assertEquals(98765432L, event.totalBytesProcessed)
        assertEquals(42.5, event.totalDurationSeconds, 0.0001)
    }

    @Test
    fun `parses a per-item error`() {
        val line = """{"message_type":"error","error":{"message":"permission denied"},
            |"during":"archival","item":"/data/data/x"}""".trimMargin().replace("\n", "")

        val event = ResticJson.parseLine(line) as ResticEvent.ItemError
        assertEquals("permission denied", event.message)
        assertEquals("archival", event.during)
        assertEquals("/data/data/x", event.item)
    }

    @Test
    fun `unmodelled message types survive as raw json`() {
        val event = ResticJson.parseLine("""{"message_type":"verbose_status","action":"new"}""")
        assertTrue(event is ResticEvent.Json)
        assertEquals("new", (event as ResticEvent.Json).obj.optString("action"))
    }

    @Test
    fun `non-json output is not swallowed`() {
        val event = ResticJson.parseLine("repository 1a2b3c opened")
        assertEquals("repository 1a2b3c opened", (event as ResticEvent.Output).line)
    }

    @Test
    fun `blank lines are dropped`() {
        assertNull(ResticJson.parseLine("   "))
    }

    @Test
    fun `malformed json degrades to output rather than throwing`() {
        val event = ResticJson.parseLine("""{"message_type":"status", oops""")
        assertTrue(event is ResticEvent.Output)
    }

    @Test
    fun `parses a snapshots array document`() {
        val doc = """
            [{"time":"2026-08-29T09:00:00.123456789+03:00","paths":["/storage/emulated/0/DCIM"],
              "hostname":"pixel","username":"u0_a123","tags":["photos"],
              "id":"aabbccddeeff00112233","short_id":"aabbccdd"}]
        """.trimIndent()

        val objects = ResticJson.parseDocument(doc)
        assertEquals(1, objects.size)

        val snapshot = ResticSnapshot.from(objects.first())
        assertEquals("aabbccdd", snapshot.shortId)
        assertEquals(listOf("photos"), snapshot.tags)
        assertEquals(listOf("/storage/emulated/0/DCIM"), snapshot.paths)
    }

    @Test
    fun `parseDocument falls back to newline delimited objects`() {
        val objects = ResticJson.parseDocument("""{"a":1}
            |{"a":2}""".trimMargin())
        assertEquals(2, objects.size)
    }

    @Test
    fun `parseDocument keeps every object, not just the first`() {
        val objects = ResticJson.parseDocument("""{"a":1}
            |{"a":2}
            |{"a":3}""".trimMargin())
        assertEquals(listOf(1, 2, 3), objects.map { it.getInt("a") })
    }

    @Test
    fun `parseDocument reads a pretty printed single object`() {
        val objects = ResticJson.parseDocument("""
            {
              "version": 2,
              "id": "aabbcc"
            }
        """.trimIndent())
        assertEquals(1, objects.size)
        assertEquals("aabbcc", objects.single().getString("id"))
    }

    @Test
    fun `empty document yields nothing`() {
        assertEquals(emptyList<Any>(), ResticJson.parseDocument("  \n "))
    }
}

class ResticResultErrorTest {
    private fun result(code: Int, stdout: String = "", stderr: String = "") =
        ResticResult(code, stdout, stderr)

    @org.junit.Test
    fun `an exit_error object becomes its message`() {
        val r = result(1, stdout = """{"message_type":"exit_error","code":1,"message":"Fatal: There were 1 errors\n"}""")
        org.junit.Assert.assertEquals("Fatal: There were 1 errors", r.humanError())
        org.junit.Assert.assertFalse(r.humanError().contains("message_type"))
    }

    @org.junit.Test
    fun `it is found on stderr too, since restic is not consistent about the stream`() {
        val r = result(1, stderr = """{"message_type":"exit_error","code":1,"message":"wrong password"}""")
        org.junit.Assert.assertEquals("wrong password", r.humanError())
    }

    @org.junit.Test
    fun `plain stderr is used when there is no json`() {
        org.junit.Assert.assertEquals(
            "Fatal: unable to open config file",
            result(1, stderr = "some warning\nFatal: unable to open config file").humanError(),
        )
    }

    @org.junit.Test
    fun `with nothing to go on it falls back to the exit code's meaning`() {
        org.junit.Assert.assertEquals(ResticExit.describe(12), result(12).humanError())
    }

    @org.junit.Test
    fun `per-item errors are counted separately from the fatal one`() {
        val r = result(
            1,
            stdout = listOf(
                """{"message_type":"error","item":"/storage","error":{"message":"operation not permitted"}}""",
                """{"message_type":"error","item":"/storage/emulated","error":{"message":"operation not permitted"}}""",
                """{"message_type":"exit_error","code":1,"message":"Fatal: There were 2 errors"}""",
            ).joinToString("\n"),
        )
        org.junit.Assert.assertEquals(2, r.itemErrors().size)
        org.junit.Assert.assertTrue(r.itemErrors().first().toString().startsWith("/storage:"))
    }

    @org.junit.Test
    fun `an item error keeps its path and its failing call apart`() {
        val r = result(
            1,
            stdout = """{"message_type":"error","item":"/storage/emulated",""" +
                """"error":{"message":"lchown /storage/emulated: no such file or directory"}}""",
        )
        val error = r.itemErrors().single()
        org.junit.Assert.assertEquals("/storage/emulated", error.item)
        org.junit.Assert.assertEquals("lchown", error.syscall)
    }
}
