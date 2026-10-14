// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The phone's colours are written twice: Ui.kt's Palette for screens built in code,
 * and res/values/colors.xml for widgets and the window theme. Both must say the
 * same thing, and the widgets must read colours rather than state them.
 */
class SaiphPaletteTest {
    private val res = listOf(File("src/main/res"), File("app/src/main/res")).first { it.isDirectory }
    private val colors = Regex("""<color name="(saiph_[a-z_]+)">#([0-9A-Fa-f]{8})</color>""")
        .findAll(File(res, "values/colors.xml").readText())
        .associate { it.groupValues[1] to it.groupValues[2].toLong(16).toInt() }

    @Test
    fun resourceColoursMatchThePalette() {
        val expected = mapOf(
            "saiph_background" to Palette.BG, "saiph_background_raised" to Palette.BG_RAISED, "saiph_card" to Palette.CARD,
            "saiph_line" to Palette.LINE, "saiph_line_strong" to Palette.LINE_STRONG, "saiph_text" to Palette.TEXT,
            "saiph_muted" to Palette.MUTED, "saiph_accent" to Palette.ACCENT, "saiph_on_accent" to Palette.ON_ACCENT,
            "saiph_tonal" to Palette.TONAL, "saiph_tonal_line" to Palette.TONAL_LINE, "saiph_on_tonal" to Palette.ON_TONAL,
            "saiph_violet" to Palette.VIOLET,
        )
        for ((name, value) in expected) assertEquals(name, Integer.toHexString(value), Integer.toHexString(colors.getValue(name)))
    }

    @Test
    fun widgetsReadSaiphColours() {
        val widgets = listOf("layout", "drawable").flatMap { folder ->
            File(res, folder).listFiles()?.toList().orEmpty().filter { it.name.startsWith("saiph_widget") }
        }
        assertTrue(widgets.size >= 5)
        for (file in widgets) assertTrue("${file.name} states a colour; use @color/saiph_*",
            !Regex("""="#[0-9A-Fa-f]{3,8}"""").containsMatchIn(file.readText()))
    }
}
