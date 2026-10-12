package sefirah.domain.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class GitHubReleaseResponse(
    @SerialName("tag_name") val tagName: String,
    @SerialName("body") val body: String? = null,
    @SerialName("html_url") val htmlUrl: String,
    @SerialName("published_at") val publishedAt: String? = null,
)
