package sefirah.domain.model

data class UpdateInfo(
    val android: List<Release>,
    val desktop: List<Release>,
    val hasAndroidUpdate: Boolean,
) {
    val latestAndroid: Release? get() = android.firstOrNull()
    val latestDesktop: Release? get() = desktop.firstOrNull()
}
