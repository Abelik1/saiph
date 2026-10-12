package com.castle.sefirah.presentation.settings.update

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBarDefaults
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.PrimaryTabRow
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Tab
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.navigation.NavController
import androidx.navigation.compose.currentBackStackEntryAsState
import com.castle.sefirah.BuildConfig
import com.castle.sefirah.navigation.Graph
import com.castle.sefirah.presentation.main.ConnectionViewModel
import kotlinx.coroutines.launch
import sefirah.common.R
import sefirah.data.repository.ReleaseRepository
import sefirah.domain.model.Release
import sefirah.presentation.components.padding
import sefirah.presentation.util.secondaryItemAlpha
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle
import java.util.Locale

private enum class UpdateTab {
    Android,
    Desktop,
}

@Composable
fun NewUpdateScreen(
    rootNavController: NavController,
) {
    val backStackState = rootNavController.currentBackStackEntryAsState().value
    val backStackEntry = remember(key1 = backStackState) {
        rootNavController.getBackStackEntry(Graph.MainScreenGraph)
    }
    val connectionViewModel: ConnectionViewModel = hiltViewModel(backStackEntry)
    val updateInfo by connectionViewModel.updateInfo.collectAsState()

    val uriHandler = LocalUriHandler.current
    val scope = rememberCoroutineScope()
    val tabs = UpdateTab.entries
    val pagerState = rememberPagerState(pageCount = { tabs.size })

    val selectedTab = tabs[pagerState.currentPage]
    val selectedReleases: List<Release> = when (selectedTab) {
        UpdateTab.Android -> updateInfo?.android.orEmpty()
        UpdateTab.Desktop -> updateInfo?.desktop.orEmpty()
    }
    val latestRelease = selectedReleases.firstOrNull()
    val hasAndroidUpdate = updateInfo?.hasAndroidUpdate == true
    val latestAndroidVersion = updateInfo?.latestAndroid?.version
    val currentVersion = BuildConfig.VERSION_NAME

    Scaffold(
        bottomBar = {
            UpdateBottomBar(
                selectedTab = selectedTab,
                onPlayStoreClick = {
                    uriHandler.openUri(ReleaseRepository.PLAY_STORE_URL)
                },
                onGithubClick = {
                    val url = latestRelease?.releaseLink
                        ?: when (selectedTab) {
                            UpdateTab.Android -> "https://github.com/shrimqy/Sefirah-Android/releases"
                            UpdateTab.Desktop -> "https://github.com/shrimqy/Sefirah/releases"
                        }
                    uriHandler.openUri(url)
                },
            )
        },
    ) { paddingValues ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(paddingValues),
        ) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(
                        horizontal = MaterialTheme.padding.medium,
                        vertical = MaterialTheme.padding.medium,
                    ),
                horizontalArrangement = Arrangement.spacedBy(MaterialTheme.padding.medium),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(
                    painter = painterResource(R.drawable.ic_new_releases),
                    contentDescription = null,
                    modifier = Modifier.size(40.dp),
                    tint = MaterialTheme.colorScheme.primary,
                )
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = if (hasAndroidUpdate) {
                            stringResource(R.string.update_check_notification_update_available)
                        } else {
                            stringResource(R.string.changelog)
                        },
                        style = MaterialTheme.typography.headlineSmall,
                    )
                    if (hasAndroidUpdate && !latestAndroidVersion.isNullOrBlank()) {
                        Text(
                            text = stringResource(
                                R.string.update_from_to_version,
                                currentVersion,
                                latestAndroidVersion,
                            ),
                            modifier = Modifier.padding(top = 2.dp),
                            style = MaterialTheme.typography.titleMedium,
                            color = MaterialTheme.colorScheme.primary,
                        )
                    }
                }
            }

            PrimaryTabRow(
                selectedTabIndex = pagerState.currentPage,
                modifier = Modifier.fillMaxWidth(),
            ) {
                tabs.forEachIndexed { index, tab ->
                    Tab(
                        selected = pagerState.currentPage == index,
                        onClick = {
                            scope.launch { pagerState.scrollToPage(index) }
                        },
                        text = {
                            Text(
                                text = when (tab) {
                                    UpdateTab.Android -> stringResource(R.string.android)
                                    UpdateTab.Desktop -> stringResource(R.string.desktop)
                                },
                            )
                        },
                    )
                }
            }

            HorizontalPager(
                state = pagerState,
                beyondViewportPageCount = 1,
                modifier = Modifier
                    .fillMaxWidth()
                    .weight(1f),
            ) { page ->
                val releases = when (tabs[page]) {
                    UpdateTab.Android -> updateInfo?.android.orEmpty()
                    UpdateTab.Desktop -> updateInfo?.desktop.orEmpty()
                }
                ReleaseNotesPage(
                    releases = releases,
                    emptyText = stringResource(R.string.update_notes_unavailable),
                )
            }
        }
    }
}

@Composable
private fun ReleaseNotesPage(
    releases: List<Release>,
    emptyText: String,
) {
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(
            horizontal = MaterialTheme.padding.medium,
            vertical = MaterialTheme.padding.large,
        ),
    ) {
        if (releases.isEmpty()) {
            item {
                Text(
                    text = emptyText,
                    modifier = Modifier.secondaryItemAlpha(),
                    style = MaterialTheme.typography.bodyMedium,
                )
            }
            return@LazyColumn
        }

        itemsIndexed(
            items = releases,
            key = { _, release -> release.releaseLink },
        ) { index, release ->
            if (index > 0) {
                HorizontalDivider(
                    modifier = Modifier.padding(vertical = MaterialTheme.padding.large),
                )
            }
            ReleaseNotesItem(
                release = release,
                emptyText = emptyText,
            )
        }
    }
}

@Composable
private fun ReleaseNotesItem(
    release: Release,
    emptyText: String,
) {
    val formattedDate = remember(release.publishedAt) {
        formatReleaseDate(release.publishedAt)
    }

    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = release.version,
            style = MaterialTheme.typography.titleMedium,
            color = MaterialTheme.colorScheme.primary,
        )
        if (formattedDate != null) {
            Text(
                text = formattedDate,
                modifier = Modifier.secondaryItemAlpha(),
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }

    if (release.info.isBlank()) {
        Text(
            text = emptyText,
            modifier = Modifier
                .secondaryItemAlpha()
                .padding(top = MaterialTheme.padding.small),
            style = MaterialTheme.typography.bodyMedium,
        )
    } else {
        ChangelogMarkdown(
            text = release.info,
            modifier = Modifier
                .fillMaxWidth()
                .padding(top = MaterialTheme.padding.small),
        )
    }
}

private fun formatReleaseDate(publishedAt: String?): String? {
    if (publishedAt.isNullOrBlank()) return null
    return try {
        val instant = Instant.parse(publishedAt)
        DateTimeFormatter
            .ofLocalizedDate(FormatStyle.MEDIUM)
            .withLocale(Locale.getDefault())
            .withZone(ZoneId.systemDefault())
            .format(instant)
    } catch (_: Exception) {
        null
    }
}

@Composable
private fun UpdateBottomBar(
    selectedTab: UpdateTab,
    onPlayStoreClick: () -> Unit,
    onGithubClick: () -> Unit,
) {
    val strokeWidth = Dp.Hairline
    val borderColor = MaterialTheme.colorScheme.outline
    Column(
        modifier = Modifier
            .background(MaterialTheme.colorScheme.background)
            .drawBehind {
                drawLine(
                    borderColor,
                    Offset(0f, 0f),
                    Offset(size.width, 0f),
                    strokeWidth.value,
                )
            }
            .windowInsetsPadding(NavigationBarDefaults.windowInsets)
            .padding(
                horizontal = MaterialTheme.padding.medium,
                vertical = MaterialTheme.padding.small,
            ),
        verticalArrangement = Arrangement.spacedBy(MaterialTheme.padding.extraSmall),
    ) {
        if (selectedTab == UpdateTab.Android) {
            Button(
                modifier = Modifier.fillMaxWidth(),
                onClick = onPlayStoreClick,
            ) {
                Text(text = stringResource(R.string.update_check_play_store))
            }
        }
        OutlinedButton(
            modifier = Modifier.fillMaxWidth(),
            onClick = onGithubClick,
        ) {
            Text(text = stringResource(R.string.update_check_open))
            Icon(
                painter = painterResource(R.drawable.ic_open_in_new),
                contentDescription = null,
                modifier = Modifier.padding(start = MaterialTheme.padding.extraSmall),
            )
        }
    }
}
