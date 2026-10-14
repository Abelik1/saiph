package com.orionmini.mobile

import android.content.Context
import android.content.res.ColorStateList
import android.graphics.Canvas
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RadialGradient
import android.graphics.Shader
import android.graphics.Typeface
import android.graphics.drawable.Drawable
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.RippleDrawable
import android.text.InputType
import android.text.TextUtils
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.ImageButton
import android.widget.LinearLayout
import android.widget.Switch
import android.widget.TextView
import java.time.Duration
import java.time.Instant
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import kotlin.math.PI
import kotlin.math.sin

/**
 * Saiph's colours, the same roles as the desktop design system
 * (frontend/src/design-system/tokens.css): deep night surfaces, a cyan main action
 * that runs through sky to violet, and status colours that never follow the brand.
 * res/values/colors.xml carries the same values for widgets and the window theme;
 * SaiphPaletteTest keeps the two in step.
 */
object Palette {
    const val BG = 0xFF040916.toInt()
    const val BG_RAISED = 0xFF081430.toInt()
    const val CARD = 0xFF0A1224.toInt()
    const val FIELD = 0xFF060D1D.toInt()
    const val MUTED_FILL = 0xFF121D36.toInt()
    const val LINE = 0xFF1A2847.toInt()
    const val LINE_STRONG = 0xFF273963.toInt()
    const val TEXT = 0xFFE7EBF4.toInt()
    const val MUTED = 0xFF909FC1.toInt()
    const val EYEBROW = 0xFF909FC1.toInt()
    const val ACCENT = 0xFF20D3EE.toInt()
    const val SKY = 0xFF61A6FA.toInt()
    const val VIOLET = 0xFFA689FA.toInt()
    const val WAVE = 0xFF67E5F9.toInt()
    const val ON_ACCENT = 0xFF050D1F.toInt()
    const val TONAL = 0xFF0C273A.toInt()
    const val TONAL_LINE = 0xFF114C61.toInt()
    const val ON_TONAL = 0xFF89EBFA.toInt()
    /** "This needs you": amber, as on the desktop. */
    const val DUE = 0xFFF7B645.toInt()
    const val DUE_SURFACE = 0xFF292728.toInt()
    const val GOOD = 0xFF6EE7B7.toInt()
    const val GOOD_SURFACE = 0xFF172E37.toInt()
    const val WARN = 0xFFFBBF24.toInt()
    const val WARN_SURFACE = 0xFF292824.toInt()
    const val BAD = 0xFFF87171.toInt()
    const val BAD_SURFACE = 0xFF291E2E.toInt()
}

/** What a button is for; each has one look across the app. */
enum class Tone { PRIMARY, SECONDARY, TONAL, DANGER }

fun Context.dp(value: Int) = (value * resources.displayMetrics.density).toInt()

fun Context.outline(fill: Int, stroke: Int, radius: Int = 12): GradientDrawable =
    GradientDrawable().apply { setColor(fill); setStroke(dp(1), stroke); cornerRadius = dp(radius).toFloat() }

/** The main action's fill: the string's cyan running through sky to violet. */
fun Context.gradientFill(radius: Int = 999): GradientDrawable =
    GradientDrawable(GradientDrawable.Orientation.TL_BR, intArrayOf(Palette.ACCENT, Palette.SKY, Palette.VIOLET))
        .apply { cornerRadius = dp(radius).toFloat() }

private fun Context.pressable(shape: Drawable, ripple: Int = 0x33FFFFFF) = RippleDrawable(ColorStateList.valueOf(ripple), shape, null)

fun Context.text(value: String, size: Float = 14f, color: Int = Palette.TEXT, bold: Boolean = false) = TextView(this).apply {
    text = value; textSize = size; setTextColor(color); setLineSpacing(0f, 1.15f)
    if (bold) setTypeface(typeface, Typeface.BOLD)
}

fun Context.eyebrow(value: String) = text(value.uppercase(), 12f, Palette.EYEBROW, true).apply { letterSpacing = 0.08f }

fun Context.heading(value: String) = text(value, 26f, Palette.TEXT, true).apply { letterSpacing = -0.02f }

fun Context.section(value: String) = eyebrow(value).apply { setPadding(dp(4), dp(22), 0, dp(8)) }

/**
 * Buttons are pills. `primary` keeps its old meaning for existing call sites:
 * the one main action on a screen. Use [tone] for the quieter looks.
 */
fun Context.button(label: String, primary: Boolean = false, tone: Tone = if (primary) Tone.PRIMARY else Tone.SECONDARY, run: () -> Unit) = Button(this).apply {
    text = label; isAllCaps = false; textSize = 14f; stateListAnimator = null
    minHeight = dp(48); minimumHeight = dp(48); minWidth = 0; minimumWidth = 0
    setPadding(dp(18), dp(10), dp(18), dp(10))
    when (tone) {
        Tone.PRIMARY -> { setTextColor(Palette.ON_ACCENT); setTypeface(typeface, Typeface.BOLD); background = pressable(gradientFill(), 0x33050D1F) }
        Tone.SECONDARY -> { setTextColor(Palette.TEXT); background = pressable(outline(Palette.CARD, Palette.LINE_STRONG, 999)) }
        Tone.TONAL -> { setTextColor(Palette.ON_TONAL); background = pressable(outline(Palette.TONAL, Palette.TONAL_LINE, 999)) }
        Tone.DANGER -> { setTextColor(Palette.BAD); background = pressable(outline(Palette.CARD, 0x73F87171, 999)) }
    }
    setOnClickListener { run() }
}

/** An icon-only button. It always carries a spoken label. */
fun Context.iconButton(icon: Int, label: String, run: () -> Unit) = ImageButton(this).apply {
    setImageResource(icon); contentDescription = label; tooltipText = label
    imageTintList = ColorStateList.valueOf(Palette.TEXT)
    background = pressable(outline(0, 0, 999), 0x33FFFFFF)
    setPadding(dp(12), dp(12), dp(12), dp(12))
    minimumWidth = dp(48); minimumHeight = dp(48)
    setOnClickListener { run() }
}

/** A short status: a dot and a word or two. */
fun Context.badge(label: String, color: Int, surface: Int) = TextView(this).apply {
    text = "●  $label"; textSize = 12f; setTextColor(color); setTypeface(typeface, Typeface.BOLD)
    background = outline(surface, surface, 999); setPadding(dp(10), dp(4), dp(12), dp(4))
}

fun Context.field(hint: String, number: Boolean = false) = EditText(this).apply {
    this.hint = hint; setHintTextColor(Palette.MUTED); setTextColor(Palette.TEXT); textSize = 15f
    background = outline(Palette.FIELD, Palette.LINE_STRONG, 12); setPadding(dp(14), dp(12), dp(14), dp(12))
    if (number) inputType = InputType.TYPE_CLASS_NUMBER
    layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
        .apply { bottomMargin = dp(10) }
}

/** A surface over the strings; `strong` for items that need a decision. */
fun Context.card(strong: Boolean = false) = LinearLayout(this).apply {
    orientation = LinearLayout.VERTICAL
    background = outline(if (strong) Palette.TONAL else 0xE60A1224.toInt(), if (strong) Palette.TONAL_LINE else Palette.LINE, 16)
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

/** Switches take Saiph's colours: cyan when on, a quiet track when off. */
fun Switch.saiph(): Switch = apply {
    val states = arrayOf(intArrayOf(android.R.attr.state_checked), intArrayOf())
    thumbTintList = ColorStateList(states, intArrayOf(Palette.ON_ACCENT, Palette.TEXT))
    trackTintList = ColorStateList(states, intArrayOf(Palette.ACCENT, Palette.LINE_STRONG))
    setTextColor(Palette.TEXT); textSize = 15f
    minHeight = context.dp(52); setPadding(context.dp(4), 0, 0, 0)
}

/** A setting: label, optional explanation, and its switch on the right. */
fun Context.switchRow(label: String, detail: String? = null, checked: Boolean, changed: (Boolean) -> Unit): View =
    LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL; setPadding(0, dp(4), 0, dp(4))
        addView(Switch(context).saiph().apply { text = label; isChecked = checked; setOnCheckedChangeListener { _, on -> changed(on) } },
            LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        detail?.let { addView(text(it, 13f, Palette.MUTED).apply { setPadding(dp(4), 0, dp(56), dp(6)) }) }
    }

/**
 * One everyday action: an icon over a short label. Used in the home screen's dock,
 * where the thumb rests, so they never sit below a long list.
 */
fun Context.dockAction(icon: Int, label: String, run: () -> Unit) = LinearLayout(this).apply {
    orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER
    contentDescription = label; isClickable = true; isFocusable = true
    background = pressable(outline(0, 0, 16))
    setPadding(dp(4), dp(10), dp(4), dp(8))
    addView(android.widget.ImageView(context).apply {
        setImageResource(icon); imageTintList = ColorStateList.valueOf(Palette.ON_TONAL)
        background = outline(Palette.TONAL, Palette.TONAL_LINE, 14); setPadding(dp(10), dp(10), dp(10), dp(10))
    }, LinearLayout.LayoutParams(dp(46), dp(46)))
    addView(text(label, 12f, Palette.TEXT).apply {
        gravity = Gravity.CENTER; maxLines = 1; ellipsize = TextUtils.TruncateAt.END; setPadding(0, dp(6), 0, 0)
        importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
    })
    setOnClickListener { run() }
}

/**
 * The strings behind every screen, as on the desktop: contour lines running from
 * cyan to violet over a night ground. Drawn once per size, never animated, so it
 * costs nothing while the screen is still.
 */
class StringField(context: Context) : View(context) {
    private val stroke = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE; strokeWidth = context.resources.displayMetrics.density }
    private val glows = listOf(Paint(Paint.ANTI_ALIAS_FLAG), Paint(Paint.ANTI_ALIAS_FLAG))
    private var strings: List<Pair<Path, Shader>> = emptyList()

    // Everything is built once per size; drawing only paints what is already made.
    override fun onSizeChanged(w: Int, h: Int, oldw: Int, oldh: Int) {
        val width = w.toFloat(); val height = h.toFloat(); val reach = maxOf(width, height)
        glows[0].shader = RadialGradient(width * 0.15f, -height * 0.05f, reach * 0.7f, 0x2220D3EE, 0, Shader.TileMode.CLAMP)
        glows[1].shader = RadialGradient(width * 1.05f, height * 1.05f, reach * 0.6f, 0x1FA689FA, 0, Shader.TileMode.CLAMP)
        val count = 18
        val gap = height / (count + 1)
        strings = (1..count).map { i ->
            val depth = i.toFloat() / (count + 1)
            // Strings fade towards the top and bottom edges.
            val level = 0.05f + 0.16f * sin(PI * depth).toFloat().let { it * it }
            val alpha = (level * 255).toInt()
            fun tint(colour: Int, share: Float) = (colour and 0xFFFFFF) or ((alpha * share).toInt() shl 24)
            val shader = LinearGradient(0f, 0f, width, 0f, intArrayOf(tint(Palette.ACCENT, 0.4f), tint(Palette.WAVE, 1f), tint(Palette.VIOLET, 0.6f)),
                floatArrayOf(0f, 0.45f, 1f), Shader.TileMode.CLAMP)
            val path = Path()
            var x = 0f
            while (x <= width + 8f) {
                val u = x / width
                val y = i * gap + sin(u * 2.6 + depth * 4.1).toFloat() * gap * 0.9f + sin(u * 6.3 - depth * 2.2).toFloat() * gap * 0.25f
                if (x == 0f) path.moveTo(x, y) else path.lineTo(x, y)
                x += 8f
            }
            path to shader
        }
    }

    override fun onDraw(canvas: Canvas) {
        canvas.drawColor(Palette.BG)
        glows.forEach { canvas.drawPaint(it) }
        strings.forEach { (path, shader) -> stroke.shader = shader; canvas.drawPath(path, stroke) }
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
