// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.animation.ValueAnimator
import android.content.Context
import android.graphics.Canvas
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.Path
import android.graphics.Shader
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout

/** Decorative, resolution-independent setup illustrations. No real pairing code is drawn. */
class SetupArtwork @JvmOverloads constructor(context: Context, private val scene: Scene = Scene.WELCOME) : View(context) {
    enum class Scene { WELCOME, SCAN, APPROVE, HUB }
    private val ink = Paint(Paint.ANTI_ALIAS_FLAG)
    private val gradient = LinearGradient(20f, 100f, 320f, 140f, Palette.ACCENT, Palette.VIOLET, Shader.TileMode.CLAMP)
    private val firstString = Path().apply { moveTo(32f, 157f); cubicTo(92f, 102f, 203f, 220f, 307f, 123f) }
    private val secondString = Path().apply { moveTo(32f, 166f); cubicTo(120f, 204f, 192f, 80f, 310f, 160f) }
    private val check = Path().apply { moveTo(124f, 97f); lineTo(134f, 108f); lineTo(154f, 87f) }
    private val finderX = floatArrayOf(112f, 151f, 112f)
    private val finderY = floatArrayOf(69f, 69f, 108f)
    private var phase = 0f
    private val motion = ValueAnimator.ofFloat(0f, 1f).apply {
        duration = 2600; repeatCount = ValueAnimator.INFINITE
        addUpdateListener { phase = it.animatedValue as Float; invalidate() }
    }
    init {
        importantForAccessibility = IMPORTANT_FOR_ACCESSIBILITY_NO
        val height = (224f / resources.configuration.fontScale.coerceAtLeast(1f)).toInt().coerceIn(120, 224)
        layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, context.dp(height))
    }
    private fun updateMotion() {
        if (isAttachedToWindow && isShown && windowVisibility == VISIBLE && ValueAnimator.areAnimatorsEnabled()) {
            if (!motion.isStarted) motion.start()
        } else { motion.cancel(); phase = 0f }
    }
    override fun onAttachedToWindow() { super.onAttachedToWindow(); updateMotion() }
    override fun onDetachedFromWindow() { motion.cancel(); super.onDetachedFromWindow() }
    override fun onWindowVisibilityChanged(visibility: Int) { super.onWindowVisibilityChanged(visibility); updateMotion() }
    override fun onVisibilityChanged(changedView: View, visibility: Int) { super.onVisibilityChanged(changedView, visibility); updateMotion() }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val scale = minOf(width / 340f, height / 224f)
        canvas.save(); canvas.translate((width - 340 * scale) / 2, (height - 224 * scale) / 2); canvas.scale(scale, scale)
        ink.shader = gradient
        ink.style = Paint.Style.STROKE; ink.strokeWidth = 2f
        canvas.drawPath(firstString, ink)
        canvas.drawPath(secondString, ink)
        ink.shader = null
        if (scene == Scene.HUB) {
            box(canvas, 69f, 34f, 230f, 157f, Palette.CARD, Palette.LINE_STRONG, 16f)
            repeat(3) { index ->
                box(canvas, 87f, 53f + index * 29, 212f, 75f + index * 29, Palette.FIELD, Palette.LINE, 6f)
                ink.style = Paint.Style.FILL; ink.color = Palette.ACCENT
                canvas.drawCircle(197f, 64f + index * 29, 3f, ink)
            }
        } else {
            box(canvas, 24f, 34f, 254f, 168f, Palette.CARD, Palette.LINE_STRONG, 14f)
            box(canvas, 36f, 46f, 242f, 151f, Palette.FIELD, Palette.LINE, 7f)
            ink.color = Palette.LINE_STRONG; ink.style = Paint.Style.STROKE; ink.strokeWidth = 5f; ink.strokeCap = Paint.Cap.ROUND
            canvas.drawLine(116f, 170f, 116f, 186f, ink); canvas.drawLine(86f, 188f, 147f, 188f, ink)
            if (scene == Scene.SCAN) {
                // Three finder shapes and sparse dots read as a QR illustration, not a scannable payload.
                box(canvas, 104f, 61f, 173f, 131f, Palette.TEXT, Palette.TEXT, 5f)
                for (index in finderX.indices) {
                    val x = finderX[index]; val y = finderY[index]
                    box(canvas, x, y, x + 14, y + 14, Palette.FIELD, Palette.FIELD, 2f)
                    ink.style = Paint.Style.FILL; ink.color = Palette.TEXT; canvas.drawRect(x + 4, y + 4, x + 10, y + 10, ink)
                }
                ink.style = Paint.Style.FILL; ink.color = Palette.FIELD
                for (row in 0..3) for (column in 0..3) if ((row + column) % 3 != 0)
                    canvas.drawRect(138f + column * 7, 98f + row * 7, 142f + column * 7, 102f + row * 7, ink)
                ink.color = Palette.ACCENT; ink.strokeWidth = 2f
                canvas.drawLine(94f, 64f + phase * 68, 183f, 64f + phase * 68, ink)
            } else {
                ink.style = Paint.Style.FILL; ink.color = Palette.TONAL
                canvas.drawCircle(139f, 97f, 30f, ink)
                ink.color = Palette.ACCENT; ink.style = Paint.Style.STROKE; ink.strokeWidth = 3f
                if (scene == Scene.APPROVE) {
                    canvas.drawPath(check, ink)
                } else {
                    canvas.drawCircle(129f, 97f, 8f, ink); canvas.drawCircle(149f, 97f, 8f, ink)
                    canvas.drawLine(134f, 97f, 144f, 97f, ink)
                }
            }
        }
        box(canvas, 237f, 80f, 308f, 202f, Palette.CARD, Palette.ACCENT, 14f)
        box(canvas, 245f, 93f, 300f, 186f, Palette.FIELD, Palette.LINE, 7f)
        ink.style = Paint.Style.FILL; ink.color = Palette.TONAL
        canvas.drawCircle(272f, 137f, 17f, ink)
        ink.color = Palette.ACCENT; canvas.drawCircle(272f, 137f, 5f + phase * 2f, ink)
        ink.color = Palette.MUTED; canvas.drawRoundRect(261f, 192f, 283f, 194f, 1f, 1f, ink)
        canvas.restore()
    }
    private fun box(canvas: Canvas, left: Float, top: Float, right: Float, bottom: Float, fill: Int, edge: Int, radius: Float) {
        ink.shader = null; ink.style = Paint.Style.FILL; ink.color = fill; canvas.drawRoundRect(left, top, right, bottom, radius, radius, ink)
        ink.style = Paint.Style.STROKE; ink.strokeWidth = 1.5f; ink.color = edge; canvas.drawRoundRect(left, top, right, bottom, radius, radius, ink)
    }
}
