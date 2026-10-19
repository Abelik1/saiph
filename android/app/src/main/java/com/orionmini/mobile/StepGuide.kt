// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import android.graphics.Typeface
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout

/**
 * Picture instructions for a screen with one main action: a few numbered pictograms, each with
 * one short line, showing what happens before and after the tap. Flat, still and drawn from the
 * palette, so they cost nothing to show and read at any size. The pictures are decorative; each
 * step's words carry the same instruction for assistive technology.
 */
enum class StepPicture { COMPUTER_TAB, SCAN_CODE, VERIFY, STREAM, COMPARE, APPROVE, ALLOW, NOTIFY, DOWNLOAD, GENUINE, CONFIRM }

data class Step(val picture: StepPicture, val title: String)

/** A vertical run of numbered steps, joined by a quiet line from one picture to the next. */
fun Context.stepGuide(vararg steps: Step): LinearLayout = LinearLayout(this).apply {
    orientation = LinearLayout.VERTICAL; setPadding(0, dp(8), 0, dp(8))
    layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
    steps.forEachIndexed { index, step ->
        if (index > 0) addView(View(context).apply { setBackgroundColor(Palette.LINE_STRONG); importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO },
            LinearLayout.LayoutParams(dp(2), dp(14)).apply { marginStart = dp(31) })
        addView(LinearLayout(context).apply {
            orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
            isFocusable = true; contentDescription = "Step ${index + 1} of ${steps.size}: ${step.title}"
            addView(StepTile(context, step.picture, index + 1), LinearLayout.LayoutParams(dp(64), dp(64)).apply { marginEnd = dp(14) })
            addView(text(step.title, UiType.BODY).apply { importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO },
                LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        })
    }
}

/** One 64 dp pictogram on a card surface, with its step number in the corner. */
class StepTile(context: Context, private val picture: StepPicture, private val number: Int) : View(context) {
    private val ink = Paint(Paint.ANTI_ALIAS_FLAG).apply { strokeCap = Paint.Cap.ROUND; strokeJoin = Paint.Join.ROUND }
    private val digits = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Palette.ON_ACCENT; textAlign = Paint.Align.CENTER; textSize = 9f; typeface = Typeface.create("sans-serif", Typeface.BOLD)
    }
    private val shape = Path()
    private val box = RectF()

    init { importantForAccessibility = IMPORTANT_FOR_ACCESSIBILITY_NO }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val scale = minOf(width, height) / 64f
        canvas.save(); canvas.scale(scale, scale)
        rect(canvas, 1f, 1f, 63f, 63f, 14f, Palette.CARD, Palette.LINE_STRONG)
        when (picture) {
            StepPicture.COMPUTER_TAB -> {
                monitor(canvas, 8f, 14f, 56f, 44f)
                // A sidebar with one lit entry: the Phone tab, then its Webcam pane.
                rect(canvas, 12f, 18f, 23f, 40f, 2f, Palette.CARD, Palette.LINE)
                rect(canvas, 14f, 26f, 21f, 30f, 1.5f, Palette.ACCENT, Palette.ACCENT)
                lens(canvas, 39f, 29f)
            }
            StepPicture.SCAN_CODE -> {
                phone(canvas, 21f, 8f, 43f, 56f)
                code(canvas, 26f, 20f)
                corners(canvas, 24f, 17f, 40f, 33f)
                stroke(Palette.ACCENT, 1.5f); canvas.drawLine(24f, 25f, 40f, 25f, ink)
            }
            StepPicture.VERIFY -> {
                phone(canvas, 21f, 8f, 43f, 56f)
                // Fingerprint: nested arcs over a soft disc.
                fill(Palette.TONAL); canvas.drawCircle(32f, 30f, 10f, ink)
                stroke(Palette.ACCENT, 1.4f)
                for (r in listOf(3f, 5.5f, 8f)) { box.set(32f - r, 30f - r, 32f + r, 30f + r); canvas.drawArc(box, 200f, 230f, false, ink) }
            }
            StepPicture.STREAM -> {
                phone(canvas, 5f, 20f, 21f, 50f)
                fill(Palette.ACCENT); canvas.drawCircle(13f, 26f, 2f, ink)
                monitor(canvas, 28f, 14f, 60f, 38f)
                // Someone on the computer's screen: the camera's picture arriving.
                fill(Palette.TONAL); canvas.drawCircle(44f, 23f, 4f, ink)
                stroke(Palette.ACCENT, 1.6f); box.set(37f, 28f, 51f, 40f); canvas.drawArc(box, 200f, 140f, false, ink)
                stroke(Palette.ACCENT, 1.4f)
                canvas.drawLine(21f, 30f, 26f, 28f, ink); canvas.drawLine(21f, 35f, 26f, 35f, ink); canvas.drawLine(21f, 40f, 26f, 42f, ink)
            }
            StepPicture.COMPARE -> {
                rect(canvas, 7f, 20f, 27f, 44f, 3f, Palette.FIELD, Palette.LINE_STRONG)
                rect(canvas, 37f, 20f, 57f, 44f, 3f, Palette.FIELD, Palette.LINE_STRONG)
                stroke(Palette.TEXT, 1.6f)
                for (y in listOf(27f, 32f, 37f)) { canvas.drawLine(11f, y, 23f, y, ink); canvas.drawLine(41f, y, 53f, y, ink) }
                stroke(Palette.ACCENT, 2f); canvas.drawLine(29f, 29f, 35f, 29f, ink); canvas.drawLine(29f, 35f, 35f, 35f, ink)
            }
            StepPicture.APPROVE -> {
                monitor(canvas, 8f, 14f, 56f, 44f)
                fill(Palette.TONAL); canvas.drawCircle(32f, 29f, 9f, ink)
                stroke(Palette.ACCENT, 2f)
                shape.reset(); shape.moveTo(27.5f, 29.5f); shape.lineTo(31f, 33f); shape.lineTo(37f, 26f); canvas.drawPath(shape, ink)
            }
            StepPicture.ALLOW -> {
                phone(canvas, 21f, 8f, 43f, 56f)
                rect(canvas, 25f, 28f, 39f, 36f, 4f, Palette.TONAL_LINE, Palette.TONAL_LINE)
                fill(Palette.ACCENT); canvas.drawCircle(35f, 32f, 3f, ink)
            }
            StepPicture.NOTIFY -> {
                phone(canvas, 5f, 20f, 21f, 50f)
                rect(canvas, 8f, 26f, 18f, 31f, 1.5f, Palette.ACCENT, Palette.ACCENT)
                monitor(canvas, 28f, 14f, 60f, 38f)
                rect(canvas, 42f, 18f, 57f, 24f, 1.5f, Palette.ACCENT, Palette.ACCENT)
                stroke(Palette.ACCENT, 1.4f); canvas.drawLine(21f, 33f, 26f, 30f, ink); canvas.drawLine(21f, 38f, 26f, 38f, ink)
            }
            StepPicture.DOWNLOAD -> {
                phone(canvas, 21f, 14f, 43f, 58f)
                // An arrow coming down into the phone.
                stroke(Palette.ACCENT, 2.2f)
                canvas.drawLine(32f, 6f, 32f, 34f, ink)
                shape.reset(); shape.moveTo(25f, 27f); shape.lineTo(32f, 34f); shape.lineTo(39f, 27f); canvas.drawPath(shape, ink)
                stroke(Palette.LINE_STRONG, 2f); canvas.drawLine(26f, 42f, 38f, 42f, ink)
            }
            StepPicture.GENUINE -> {
                // A shield with a tick: the signed, published build.
                shape.reset(); shape.moveTo(32f, 12f); shape.lineTo(47f, 18f); shape.lineTo(47f, 31f)
                shape.cubicTo(47f, 41f, 40f, 48f, 32f, 52f); shape.cubicTo(24f, 48f, 17f, 41f, 17f, 31f); shape.lineTo(17f, 18f); shape.close()
                fill(Palette.TONAL); canvas.drawPath(shape, ink)
                stroke(Palette.ACCENT, 1.6f); canvas.drawPath(shape, ink)
                stroke(Palette.ACCENT, 2.2f)
                shape.reset(); shape.moveTo(25.5f, 31.5f); shape.lineTo(30f, 36f); shape.lineTo(39f, 26f); canvas.drawPath(shape, ink)
            }
            StepPicture.CONFIRM -> {
                phone(canvas, 21f, 8f, 43f, 56f)
                // Android's own dialog, with its confirming button lit.
                rect(canvas, 24f, 22f, 40f, 42f, 2f, Palette.CARD, Palette.LINE_STRONG)
                stroke(Palette.TEXT, 1.2f); canvas.drawLine(27f, 27f, 37f, 27f, ink); canvas.drawLine(27f, 31f, 34f, 31f, ink)
                rect(canvas, 31f, 35f, 38f, 39f, 1.5f, Palette.ACCENT, Palette.ACCENT)
            }
        }
        // The step number, so the order reads at a glance like assembly instructions.
        fill(Palette.ACCENT); canvas.drawCircle(10f, 10f, 7f, ink)
        canvas.drawText(number.toString(), 10f, 13.2f, digits)
        canvas.restore()
    }

    private fun fill(color: Int) { ink.style = Paint.Style.FILL; ink.color = color }
    private fun stroke(color: Int, width: Float) { ink.style = Paint.Style.STROKE; ink.color = color; ink.strokeWidth = width }
    private fun rect(canvas: Canvas, l: Float, t: Float, r: Float, b: Float, radius: Float, fill: Int, edge: Int) {
        box.set(l, t, r, b)
        fill(fill); canvas.drawRoundRect(box, radius, radius, ink)
        stroke(edge, 1.2f); canvas.drawRoundRect(box, radius, radius, ink)
    }
    private fun monitor(canvas: Canvas, l: Float, t: Float, r: Float, b: Float) {
        rect(canvas, l, t, r, b, 3f, Palette.FIELD, Palette.LINE_STRONG)
        stroke(Palette.LINE_STRONG, 2f)
        val middle = (l + r) / 2
        canvas.drawLine(middle, b, middle, b + 6f, ink); canvas.drawLine(middle - 7f, b + 6f, middle + 7f, b + 6f, ink)
    }
    private fun phone(canvas: Canvas, l: Float, t: Float, r: Float, b: Float) {
        rect(canvas, l, t, r, b, 4f, Palette.FIELD, Palette.ACCENT)
        stroke(Palette.MUTED, 1.2f); val middle = (l + r) / 2; canvas.drawLine(middle - 3f, b - 3f, middle + 3f, b - 3f, ink)
    }
    private fun lens(canvas: Canvas, x: Float, y: Float) {
        rect(canvas, x - 9f, y - 6f, x + 6f, y + 6f, 2f, Palette.TONAL, Palette.TONAL_LINE)
        shape.reset(); shape.moveTo(x + 6f, y - 3f); shape.lineTo(x + 11f, y - 6f); shape.lineTo(x + 11f, y + 6f); shape.lineTo(x + 6f, y + 3f); shape.close()
        fill(Palette.ACCENT); canvas.drawPath(shape, ink)
    }
    /** Three finder squares and a few dots: a drawing of a code, never a scannable one. */
    private fun code(canvas: Canvas, x: Float, y: Float) {
        fill(Palette.TEXT)
        for ((dx, dy) in listOf(0f to 0f, 7f to 0f, 0f to 7f)) canvas.drawRect(x + dx, y + dy, x + dx + 4f, y + dy + 4f, ink)
        canvas.drawRect(x + 8f, y + 8f, x + 10f, y + 10f, ink); canvas.drawRect(x + 10.5f, y + 6f, x + 12f, y + 7.5f, ink)
    }
    private fun corners(canvas: Canvas, l: Float, t: Float, r: Float, b: Float) {
        stroke(Palette.ACCENT, 1.6f)
        val arm = 4f
        canvas.drawLine(l, t, l + arm, t, ink); canvas.drawLine(l, t, l, t + arm, ink)
        canvas.drawLine(r, t, r - arm, t, ink); canvas.drawLine(r, t, r, t + arm, ink)
        canvas.drawLine(l, b, l + arm, b, ink); canvas.drawLine(l, b, l, b - arm, ink)
        canvas.drawLine(r, b, r - arm, b, ink); canvas.drawLine(r, b, r, b - arm, ink)
    }
}
