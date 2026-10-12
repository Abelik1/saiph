package sefirah.data.repository

import android.util.Log
import io.ktor.client.call.body
import io.ktor.client.request.get
import io.ktor.client.request.parameter
import io.ktor.http.ContentType
import io.ktor.http.contentType
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.flow.first
import sefirah.domain.interfaces.PreferencesRepository
import sefirah.domain.model.GitHubReleaseResponse
import sefirah.domain.model.Release
import sefirah.domain.model.UpdateInfo
import sefirah.network.NetworkHelper
import java.time.Instant
import java.time.temporal.ChronoUnit
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class ReleaseRepository @Inject constructor(
    private val preferencesRepository: PreferencesRepository,
    private val networkHelper: NetworkHelper
) {
    suspend fun getRelease(currentVersion: String, force: Boolean = false): Result {
        try {
            if (!force) {
                val lastChecked = preferencesRepository.readLastCheckedForUpdate().first()
                val now = Instant.now()
                val nextCheckTime = Instant.ofEpochMilli(lastChecked).plus(3, ChronoUnit.DAYS)
                if (now.isBefore(nextCheckTime)) {
                    return Result.NoNewUpdate()
                }
            }

            val updateInfo = fetchReleases(currentVersion)
            if (updateInfo.android.isEmpty() && updateInfo.desktop.isEmpty()) {
                return Result.Error
            }

            preferencesRepository.saveLastCheckedForUpdate(Instant.now().toEpochMilli())

            return if (updateInfo.hasAndroidUpdate) {
                Log.d(TAG, "New Android update available: ${updateInfo.latestAndroid?.version}")
                Result.NewUpdate(updateInfo)
            } else {
                Result.NoNewUpdate(updateInfo)
            }
        } catch (e: Exception) {
            Log.e(TAG, "Failed to check for updates", e)
            return Result.Error
        }
    }

    private suspend fun fetchReleases(currentVersion: String): UpdateInfo = coroutineScope {
        val androidDeferred = async { fetchGithubReleases(ANDROID_REPO) }
        val desktopDeferred = async { fetchGithubReleases(DESKTOP_REPO) }

        val androidReleases = androidDeferred.await()
        val desktopReleases = desktopDeferred.await()
        val latestAndroid = androidReleases.firstOrNull()

        UpdateInfo(
            android = androidReleases,
            desktop = desktopReleases,
            hasAndroidUpdate = latestAndroid != null &&
                isNewVersion(currentVersion, latestAndroid.version),
        )
    }

    private suspend fun fetchGithubReleases(repo: String): List<Release> {
        return try {
            val response = networkHelper.client.get(
                "https://api.github.com/repos/$repo/releases"
            ) {
                parameter("per_page", RELEASES_PER_PAGE)
                contentType(ContentType.Application.Json)
            }
            val githubReleases: List<GitHubReleaseResponse> = response.body()
            githubReleases.map { githubRelease ->
                Release(
                    version = githubRelease.tagName,
                    info = githubRelease.body.orEmpty().trim(),
                    releaseLink = githubRelease.htmlUrl,
                    publishedAt = githubRelease.publishedAt,
                )
            }
        } catch (e: Exception) {
            Log.e(TAG, "Failed to fetch releases for $repo", e)
            emptyList()
        }
    }

    private fun isNewVersion(
        versionName: String,
        versionTag: String,
    ): Boolean {
        // Removes prefixes like "v"
        val newVersion = versionTag.replace("[^\\d.]".toRegex(), "")
        val oldVersion = versionName.replace("[^\\d.]".toRegex(), "")

        val newSemVer = newVersion.split(".").map { it.toIntOrNull() ?: 0 }
        val oldSemVer = oldVersion.split(".").map { it.toIntOrNull() ?: 0 }

        // Fix the comparison logic
        for (i in 0 until minOf(newSemVer.size, oldSemVer.size)) {
            if (newSemVer[i] > oldSemVer[i]) {
                return true
            } else if (newSemVer[i] < oldSemVer[i]) {
                return false
            }
        }
        
        // If all common segments are equal, the longer one is newer
        return newSemVer.size > oldSemVer.size
    }

    sealed interface Result {
        data class NewUpdate(val updateInfo: UpdateInfo) : Result
        data class NoNewUpdate(val updateInfo: UpdateInfo? = null) : Result
        data object Error : Result
    }

    companion object {
        private const val TAG = "ReleaseRepository"
        private const val ANDROID_REPO = "shrimqy/Sefirah-Android"
        private const val DESKTOP_REPO = "shrimqy/Sefirah"
        private const val RELEASES_PER_PAGE = 10

        const val PLAY_STORE_URL =
            "https://play.google.com/store/apps/details?id=com.castle.sefirah"
    }
}
