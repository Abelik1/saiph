package io.github.resticdroid.restic

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ResticCommandTest {
    @Test
    fun `backup places a double dash before paths`() {
        val cmd = ResticCommand.backup(listOf("/storage/emulated/0/-weird"))
        val dash = cmd.args.indexOf("--")
        assertTrue(dash > 0)
        assertEquals("/storage/emulated/0/-weird", cmd.args.last())
    }

    @Test
    fun `backup emits one exclude flag per pattern`() {
        val cmd = ResticCommand.backup(
            paths = listOf("/a"),
            excludes = listOf("*.tmp", "/a/cache"),
            tags = listOf("auto", "photos"),
        )
        assertEquals(2, cmd.args.count { it == "--exclude" })
        assertEquals(2, cmd.args.count { it == "--tag" })
        assertTrue(cmd.args.containsAll(listOf("*.tmp", "/a/cache", "auto", "photos")))
    }

    @Test
    fun `backup excludes caches by default`() {
        assertTrue(ResticCommand.backup(listOf("/a")).args.contains("--exclude-caches"))
    }

    @Test
    fun `json commands are flagged as such`() {
        assertTrue(ResticCommand.backup(listOf("/a")).json)
        assertTrue(ResticCommand.snapshots().json)
        assertTrue(!ResticCommand.version().json)
        assertTrue(!ResticCommand.check().json)
    }

    @Test
    fun `backup rejects an empty path list`() {
        val thrown = runCatching { ResticCommand.backup(emptyList()) }.exceptionOrNull()
        assertTrue(thrown is IllegalArgumentException)
    }

    @Test
    fun `retention policy renders only the fields that are set`() {
        val args = RetentionPolicy(daily = 7, monthly = 6).args()
        assertEquals(listOf("--keep-daily", "7", "--keep-monthly", "6"), args)
    }

    @Test
    fun `an empty retention policy keeps everything`() {
        assertTrue(RetentionPolicy().isEmpty())
        assertEquals(emptyList<String>(), RetentionPolicy().args())
        assertTrue(!RetentionPolicy.Default.isEmpty())
    }

    @Test
    fun `restore carries the target directory`() {
        val cmd = ResticCommand.restore("aabbccdd", "/storage/emulated/0/Restored")
        assertTrue(cmd.args.containsAll(listOf("restore", "aabbccdd", "--target", "/storage/emulated/0/Restored")))
    }
}

class ResticCommandSeparatorTest {
    @org.junit.Test
    fun `restore keeps every flag before the separator`() {
        val cmd = ResticCommand.restore("abc123", "/storage/emulated/0/Restored", overwrite = "never")
        val dash = cmd.args.indexOf("--")
        org.junit.Assert.assertTrue("expected a -- separator", dash > 0)
        listOf("--json", "--target", "--overwrite").forEach {
            org.junit.Assert.assertTrue("$it must precede --", cmd.args.indexOf(it) < dash)
        }
        org.junit.Assert.assertEquals("abc123", cmd.args.last())
        org.junit.Assert.assertEquals(
            "/storage/emulated/0/Restored",
            cmd.args[cmd.args.indexOf("--target") + 1],
        )
    }

    @org.junit.Test
    fun `ls puts its positionals after the separator`() {
        val cmd = ResticCommand.ls("abc123", "-weird-dir")
        val dash = cmd.args.indexOf("--")
        org.junit.Assert.assertTrue(cmd.args.indexOf("--json") < dash)
        org.junit.Assert.assertEquals(listOf("abc123", "-weird-dir"), cmd.args.drop(dash + 1))
    }

    @org.junit.Test
    fun `a snapshot id that looks like a flag stays a positional`() {
        val cmd = ResticCommand.restore("--no-lock", "/tmp/x")
        org.junit.Assert.assertEquals("--no-lock", cmd.args.last())
        org.junit.Assert.assertTrue(cmd.args[cmd.args.lastIndex - 1] == "--")
    }

    @org.junit.Test
    fun `forget by id puts the ids after the separator`() {
        val c = ResticCommand.forget(listOf("abc123", "def456"))
        org.junit.Assert.assertEquals(
            listOf("forget", "--json", "--", "abc123", "def456"), c.args,
        )
    }

    @org.junit.Test
    fun `forget by id can prune, and the flag stays before the separator`() {
        val c = ResticCommand.forget(listOf("abc123"), prune = true)
        org.junit.Assert.assertEquals(
            listOf("forget", "--json", "--prune", "--", "abc123"), c.args,
        )
    }

    @org.junit.Test
    fun `diff takes two snapshots and is not json`() {
        val c = ResticCommand.diff("aaa", "bbb")
        org.junit.Assert.assertEquals(listOf("diff", "--", "aaa", "bbb"), c.args)
        org.junit.Assert.assertFalse(c.json)
    }

    @org.junit.Test
    fun `stats can be scoped to one snapshot`() {
        org.junit.Assert.assertEquals(
            listOf("stats", "--json", "--mode", "restore-size", "--", "aaa"),
            ResticCommand.stats(snapshot = "aaa").args,
        )
    }

    @Test
    fun `retention is scoped by tag, grouped, and pruned`() {
        val c = ResticCommand.forget(
            policy = RetentionPolicy(last = 3),
            tags = listOf("Phone,Data"),
            groupBy = "tags",
            prune = true,
        )
        assertEquals(
            listOf(
                "forget", "--json", "--keep-last", "3",
                "--tag", "Phone,Data", "--group-by", "tags", "--prune",
            ),
            c.args,
        )
    }

    @Test
    fun `grouping is left to restic when the profile does not ask for it`() {
        val c = ResticCommand.forget(RetentionPolicy(last = 3), listOf("Data"), prune = false)
        assertEquals(listOf("forget", "--json", "--keep-last", "3", "--tag", "Data"), c.args)
    }

    @Test(expected = IllegalArgumentException::class)
    fun `an unscoped forget would apply to the whole repository, so it is refused`() {
        ResticCommand.forget(RetentionPolicy(last = 3), emptyList())
    }

    @Test(expected = IllegalArgumentException::class)
    fun `a blank scope is refused for the same reason`() {
        ResticCommand.forget(RetentionPolicy(last = 3), listOf(""))
    }
}
