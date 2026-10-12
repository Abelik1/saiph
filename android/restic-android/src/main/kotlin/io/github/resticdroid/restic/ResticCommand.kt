package io.github.resticdroid.restic

public class ResticCommand private constructor(
    public val args: List<String>,
    public val json: Boolean,
) {
    override fun toString(): String = "restic ${args.joinToString(" ")}"

    public companion object {
        public fun version(): ResticCommand = ResticCommand(listOf("version"), false)

        public fun init(): ResticCommand = ResticCommand(listOf("init", "--json"), true)

        public fun catConfig(): ResticCommand = ResticCommand(listOf("cat", "config"), true)

        public fun backup(
            paths: List<String>,
            excludes: List<String> = emptyList(),
            excludeFiles: List<String> = emptyList(),
            excludeCaches: Boolean = true,
            tags: List<String> = emptyList(),
            host: String? = null,
        ): ResticCommand {
            require(paths.isNotEmpty()) { "backup needs at least one path" }
            val a = mutableListOf("backup", "--json")
            if (excludeCaches) a += "--exclude-caches"
            host?.let { a += listOf("--host", it) }
            excludes.forEach { a += listOf("--exclude", it) }
            excludeFiles.forEach { a += listOf("--exclude-file", it) }
            tags.forEach { a += listOf("--tag", it) }
            // restic parses flags only before "--"; positionals only after it.
            a += "--"
            a += paths
            return ResticCommand(a, true)
        }

        public fun snapshots(tags: List<String> = emptyList(), host: String? = null): ResticCommand {
            val a = mutableListOf("snapshots", "--json")
            tags.forEach { a += listOf("--tag", it) }
            host?.let { a += listOf("--host", it) }
            return ResticCommand(a, true)
        }

        public fun ls(snapshot: String, path: String? = null): ResticCommand {
            val a = mutableListOf("ls", "--json", "--", snapshot)
            path?.let { a += it }
            return ResticCommand(a, true)
        }

        public fun restore(
            snapshot: String,
            target: String,
            overwrite: String? = null,
        ): ResticCommand {
            val a = mutableListOf("restore", "--json", "--target", target)
            overwrite?.let { a += listOf("--overwrite", it) }
            a += "--"
            a += snapshot
            return ResticCommand(a, true)
        }

        /**
         * Retention over the snapshots matching [tags].
         *
         * Each entry is one --tag, which restic reads as a comma-separated
         * list of tags a snapshot must carry all of; separate entries are
         * alternatives. There is no unscoped form on purpose: forget without
         * --tag applies the policy to every snapshot in the repository,
         * including those written by other devices sharing it.
         *
         * [groupBy] is restic's --group-by. Left out, restic groups by host
         * and paths, so editing what a profile backs up leaves the older
         * snapshots in a group of their own that never ages out. "tags" groups
         * by the snapshot's whole tag set instead, and "" disables grouping.
         */
        public fun forget(
            policy: RetentionPolicy,
            tags: List<String>,
            groupBy: String? = null,
            prune: Boolean = true,
        ): ResticCommand {
            require(tags.isNotEmpty() && tags.none { it.isBlank() }) {
                "forget must be scoped by tag, or it applies to the whole repository"
            }
            val a = mutableListOf("forget", "--json")
            a += policy.args()
            tags.forEach { a += listOf("--tag", it) }
            groupBy?.let { a += listOf("--group-by", it) }
            if (prune) a += "--prune"
            return ResticCommand(a, true)
        }

        public fun forget(snapshots: List<String>, prune: Boolean = false): ResticCommand {
            require(snapshots.isNotEmpty()) { "forget needs at least one snapshot" }
            val a = mutableListOf("forget", "--json")
            if (prune) a += "--prune"
            a += "--"
            a += snapshots
            return ResticCommand(a, true)
        }

        public fun prune(): ResticCommand = ResticCommand(listOf("prune"), false)

        // Plain text, not --json: restic's own diff output is already the
        // report a person wants to read, and parsing it back into one would
        // only risk disagreeing with it.
        public fun diff(from: String, to: String): ResticCommand =
            ResticCommand(listOf("diff", "--", from, to), false)

        public fun check(readData: Boolean = false): ResticCommand {
            val a = mutableListOf("check")
            if (readData) a += "--read-data"
            return ResticCommand(a, false)
        }

        public fun stats(mode: String = "restore-size", snapshot: String? = null): ResticCommand {
            val a = mutableListOf("stats", "--json", "--mode", mode)
            snapshot?.let { a += listOf("--", it) }
            return ResticCommand(a, true)
        }
    }
}

public data class RetentionPolicy(
    val last: Int? = null,
    val hourly: Int? = null,
    val daily: Int? = null,
    val weekly: Int? = null,
    val monthly: Int? = null,
    val yearly: Int? = null,
    val within: String? = null,
) {
    public fun isEmpty(): Boolean =
        last == null && hourly == null && daily == null &&
            weekly == null && monthly == null && yearly == null && within == null

    public fun args(): List<String> = buildList {
        last?.let { addAll(listOf("--keep-last", it.toString())) }
        hourly?.let { addAll(listOf("--keep-hourly", it.toString())) }
        daily?.let { addAll(listOf("--keep-daily", it.toString())) }
        weekly?.let { addAll(listOf("--keep-weekly", it.toString())) }
        monthly?.let { addAll(listOf("--keep-monthly", it.toString())) }
        yearly?.let { addAll(listOf("--keep-yearly", it.toString())) }
        within?.let { addAll(listOf("--keep-within", it)) }
    }

    public companion object {
        public val Default: RetentionPolicy =
            RetentionPolicy(last = 3, daily = 14, weekly = 12, monthly = 12, yearly = 3)
    }
}
