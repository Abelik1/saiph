package sefirah.domain.model

/**
 * Contains information about a release.
 */
data class Release(
    val version: String,
    val info: String,
    val releaseLink: String,
    val publishedAt: String? = null,
)
