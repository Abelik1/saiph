package io.github.resticdroid.restic

public data class ResticRepository(
    val uri: String,
    val password: String,
    val env: Map<String, String> = emptyMap(),
    val options: List<String> = emptyList(),
) {
    init {
        require(uri.isNotBlank()) { "repository uri must not be blank" }
    }

    override fun toString(): String = "ResticRepository(uri=${redactedUri()}, env=${env.keys})"

    public fun redactedUri(): String =
        uri.replace(Regex("""([a-zA-Z][a-zA-Z0-9+.\-]*://)[^/\s@]+@"""), "$1***@")
}
