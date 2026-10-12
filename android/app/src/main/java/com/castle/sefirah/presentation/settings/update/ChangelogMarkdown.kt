package com.castle.sefirah.presentation.settings.update

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.SpanStyle
import com.halilibo.richtext.markdown.Markdown
import com.halilibo.richtext.ui.RichTextStyle
import com.halilibo.richtext.ui.material3.RichText
import com.halilibo.richtext.ui.string.RichTextStringStyle

/**
 * Release-notes renderer using compose-richtext
 */
@Composable
fun ChangelogMarkdown(
    text: String,
    modifier: Modifier = Modifier,
) {
    RichText(
        modifier = modifier.fillMaxWidth(),
        style = RichTextStyle(
            stringStyle = RichTextStringStyle(
                linkStyle = SpanStyle(color = MaterialTheme.colorScheme.primary),
            ),
        ),
    ) {
        Markdown(content = text)
    }
}
