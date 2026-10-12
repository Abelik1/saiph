package io.github.resticdroid.restic

private const val REST_USER_KEY = "rest-user"
private const val REST_PASSWORD_KEY = "rest-password"

// No sftp or rclone: restic implements them by spawning ssh and rclone,
// which stock Android does not have and cannot be given - restic is run
// with PATH=/system/bin:/system/xbin and nothing else.
public enum class ResticBackend(
    public val id: String,
    public val displayName: String,
    public val scheme: String,
    public val credentials: List<CredentialField>,
    public val locationHint: String,
) {
    B2(
        id = "b2",
        displayName = "Backblaze B2",
        scheme = "b2:",
        credentials = listOf(
            CredentialField("B2_ACCOUNT_ID", "Application key ID", secret = false),
            CredentialField("B2_ACCOUNT_KEY", "Application key", secret = true),
        ),
        locationHint = "bucket-name:path/on/bucket",
    ),

    LOCAL(
        id = "local",
        displayName = "Local folder",
        scheme = "",
        credentials = emptyList(),
        locationHint = "/storage/emulated/0/Backups/restic",
    ),

    REST(
        id = "rest",
        displayName = "REST server",
        scheme = "rest:",
        credentials = listOf(
            CredentialField(
                REST_USER_KEY, "Username",
                secret = false, optional = true, delivery = Delivery.UrlUser,
            ),
            CredentialField(
                REST_PASSWORD_KEY, "Password",
                secret = true, optional = true, delivery = Delivery.UrlPassword,
            ),
        ),
        locationHint = "https://host:8000/path/",
    ),

    S3(
        id = "s3",
        displayName = "S3 / MinIO / Wasabi",
        scheme = "s3:",
        credentials = listOf(
            CredentialField("AWS_ACCESS_KEY_ID", "Access key ID", secret = false),
            CredentialField("AWS_SECRET_ACCESS_KEY", "Secret access key", secret = true),
            CredentialField("AWS_DEFAULT_REGION", "Region", secret = false, optional = true),
            CredentialField("AWS_SESSION_TOKEN", "Session token", secret = true, optional = true),
        ),
        locationHint = "s3.amazonaws.com/bucket-name",
    ),

    AZURE(
        id = "azure",
        displayName = "Azure Blob Storage",
        scheme = "azure:",
        credentials = listOf(
            CredentialField("AZURE_ACCOUNT_NAME", "Account name", secret = false),
            CredentialField("AZURE_ACCOUNT_KEY", "Account key", secret = true, optional = true),
            CredentialField("AZURE_ACCOUNT_SAS", "SAS token", secret = true, optional = true),
        ),
        locationHint = "container-name:/path",
    ),

    GS(
        id = "gs",
        displayName = "Google Cloud Storage",
        scheme = "gs:",
        credentials = listOf(
            CredentialField("GOOGLE_PROJECT_ID", "Project ID", secret = false),
            CredentialField(
                "GOOGLE_APPLICATION_CREDENTIALS",
                "Service-account JSON (paste the file's contents)",
                secret = true,
                delivery = Delivery.PrivateFile,
            ),
        ),
        locationHint = "bucket-name:/path",
    ),

    SWIFT(
        id = "swift",
        displayName = "OpenStack Swift",
        scheme = "swift:",
        credentials = listOf(
            CredentialField("OS_AUTH_URL", "Auth URL", secret = false),
            CredentialField("OS_USERNAME", "Username", secret = false),
            CredentialField("OS_PASSWORD", "Password", secret = true),
            CredentialField("OS_TENANT_NAME", "Tenant", secret = false, optional = true),
        ),
        locationHint = "container-name:/path",
    );

    // LOCAL needs no special case: its scheme is empty, and every string
    // starts with the empty string.
    public fun uriFor(location: String): String {
        val trimmed = location.trim()
        return if (trimmed.startsWith(scheme)) trimmed else scheme + trimmed
    }

    public companion object {
        public const val REST_USER: String = REST_USER_KEY
        public const val REST_PASSWORD: String = REST_PASSWORD_KEY

        public fun byId(id: String): ResticBackend? = entries.firstOrNull { it.id == id }

        public fun detect(uri: String): ResticBackend =
            entries.firstOrNull { it.scheme.isNotEmpty() && uri.startsWith(it.scheme) }
                ?: LOCAL
    }
}

public data class CredentialField(
    val key: String,
    val label: String,
    val secret: Boolean,
    val optional: Boolean = false,
    val delivery: Delivery = Delivery.Environment,
)

public enum class Delivery {
    Environment,

    UrlUser,

    UrlPassword,

    PrivateFile,
}
