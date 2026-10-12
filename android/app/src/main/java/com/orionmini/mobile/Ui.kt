package com.orionmini.mobile

import android.content.Context
import android.content.res.ColorStateList
import android.graphics.Typeface
import android.graphics.drawable.Drawable
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.RippleDrawable
import android.text.InputType
import android.view.Gravity
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import java.time.Duration
import java.time.Instant
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/** Shared charcoal surfaces and a blue/cyan accent, with outlined controls. */
object Palette {
    const val BG = 0xFF111315.toInt()
    const val CARD = 0xFF1A1E22.toInt()
    const val FIELD = 0xFF16191C.toInt()
    const val LINE = 0xFF2B3036.toInt()
    const val LINE_STRONG = 0xFF43515E.toInt()
    const val TEXT = 0xFFE4E6E9.toInt()
    const val MUTED = 0xFF8C939C.toInt()
    const val EYEBROW = 0xFF8C939C.toInt()
    const val ACCENT = 0xFF4CC2FF.toInt()
    const val ON_ACCENT = 0xFF10212C.toInt()
    const val DUE = 0xFFE08B73.toInt()
}

fun Context.dp(value: Int) = (value * resources.displayMetrics.density).toInt()

fun Context.outline(fill: Int, stroke: Int, radius: Int = 12): GradientDrawable =
    GradientDrawable().apply { setColor(fill); setStroke(dp(1), stroke); cornerRadius = dp(radius).toFloat() }

private fun Context.pressable(shape: Drawable) = RippleDrawable(ColorStateList.valueOf(0x33FFFFFF), shape, null)

fun Context.text(value: String, size: Float = 14f, color: Int = Palette.TEXT, bold: Boolean = false) = TextView(this).apply {
    text = value; textSize = size; setTextColor(color)
    if (bold) setTypeface(typeface, Typeface.BOLD)
}

fun Context.eyebrow(value: String) = text(value.uppercase(), 10f, Palette.EYEBROW, true).apply { letterSpacing = 0.15f }

fun Context.heading(value: String) = text(value, 26f, Palette.TEXT, true)

fun Context.section(value: String) = eyebrow(value).apply { setPadding(dp(4), dp(22), 0, dp(8)) }

/** Primary actions use cyan; secondary actions use outlined charcoal. */
fun Context.button(label: String, primary: Boolean = false, run: () -> Unit) = Button(this).apply {
    text = label; isAllCaps = false; textSize = 14f; stateListAnimator = null
    minHeight = dp(48); minimumHeight = dp(48); minWidth = 0; minimumWidth = 0
    setPadding(dp(16), dp(10), dp(16), dp(10))
    setTextColor(if (primary) Palette.ON_ACCENT else Palette.TEXT)
    if (primary) setTypeface(typeface, Typeface.BOLD)
    background = pressable(outline(if (primary) Palette.ACCENT else Palette.CARD, if (primary) Palette.ACCENT else Palette.LINE_STRONG, 10))
    setOnClickListener { run() }
}

fun Context.field(hint: String, number: Boolean = false) = EditText(this).apply {
    this.hint = hint; setHintTextColor(Palette.MUTED); setTextColor(Palette.TEXT); textSize = 15f
    background = outline(Palette.FIELD, Palette.LINE, 10); setPadding(dp(14), dp(12), dp(14), dp(12))
    if (number) inputType = InputType.TYPE_CLASS_NUMBER
    layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
        .apply { bottomMargin = dp(10) }
}

/** A bordered card; `strong` for items that need a decision. */
fun Context.card(strong: Boolean = false) = LinearLayout(this).apply {
    orientation = LinearLayout.VERTICAL
    background = outline(Palette.CARD, if (strong) Palette.LINE_STRONG else Palette.LINE, 14)
    setPadding(dp(16), dp(14), dp(16), dp(14))
    layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
        .apply { bottomMargin = dp(10) }
}

fun Context.buttonRow(vararg buttons: Button) = LinearLayout(this).apply {
    orientation = LinearLayout.HORIZONTAL; gravity = Gravity.START; setPadding(0, dp(12), 0, 0)
    buttons.forEachIndexed { i, b ->
        addView(b, LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT)
            .apply { if (i > 0) marginStart = dp(8) })
    }
}

object When {
    private val day = DateTimeFormatter.ofPattern("EEE d MMM")
    private val dayTime = DateTimeFormatter.ofPattern("EEE d MMM, HH:mm")

    /** "3 min ago", "2 h ago", "4 d ago". */
    fun ago(iso: String): String = runCatching {
        val seconds = Duration.between(OffsetDateTime.parse(iso).toInstant(), Instant.now()).seconds
        when {
            seconds < 60 -> "just now"
            seconds < 3600 -> "${seconds / 60} min ago"
            seconds < 86400 -> "${seconds / 3600} h ago"
            else -> "${seconds / 86400} d ago"
        }
    }.getOrDefault("")

    /** A proposed event's start: a date, or a date and time with or without an offset. */
    fun event(start: String, allDay: Boolean): String = runCatching {
        if (allDay || start.length == 10) LocalDate.parse(start.take(10)).format(day)
        else runCatching { OffsetDateTime.parse(start).atZoneSameInstant(ZoneId.systemDefault()).format(dayTime) }
            .getOrElse { LocalDateTime.parse(start).format(dayTime) }
    }.getOrDefault(start)

    fun reminder(minutes: Int): String {
        if (minutes == 0) return "at the start"
        val (size, name) = listOf(10080 to "week", 1440 to "day", 60 to "hour", 1 to "minute").first { minutes % it.first == 0 }
        val count = minutes / size
        return "$count $name${if (count == 1) "" else "s"} before"
    }
}
