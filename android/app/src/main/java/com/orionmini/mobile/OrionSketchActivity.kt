// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.app.AlertDialog
import android.content.Context
import android.graphics.*
import android.os.Bundle
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.lifecycle.lifecycleScope
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.*
import sefirah.network.orion.OrionDirectFiles
import java.io.File
import java.util.UUID
import javax.inject.Inject

/** Draw, or mark up a photo, and send it to a computer's clipboard (Continuity Sketch / Markup). */
@AndroidEntryPoint
class OrionSketchActivity : ComponentActivity() {
    @Inject lateinit var files: OrionDirectFiles
    private lateinit var canvas: SketchView
    private val pickPhoto = registerForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        if (uri != null) lifecycleScope.launch {
            val bitmap = withContext(Dispatchers.IO) { runCatching {
                // Bounded decode: large camera photos are sampled down before drawing.
                val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
                contentResolver.openInputStream(uri)!!.use { BitmapFactory.decodeStream(it, null, bounds) }
                var sample = 1; while (maxOf(bounds.outWidth, bounds.outHeight) / sample > 2048) sample *= 2
                contentResolver.openInputStream(uri)!!.use { BitmapFactory.decodeStream(it, null, BitmapFactory.Options().apply { inSampleSize = sample }) }
            }.getOrNull() }
            if (bitmap == null) Toast.makeText(this@OrionSketchActivity, "This picture could not be opened.", Toast.LENGTH_LONG).show() else canvas.background(bitmap)
        }
    }
    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        canvas = SketchView(this)
        // Back in the header leaves without sending; the tools stay compact so the canvas gets the room.
        val frame = ScreenFrame(this, "Sketch", back = ::finish, scrolling = false)
        val root = frame.content
        root.addView(buttonRow(compactButton("Black", Tone.SECONDARY) { canvas.color = Color.BLACK }, compactButton("Red", Tone.SECONDARY) { canvas.color = Color.RED },
            compactButton("Blue", Tone.SECONDARY) { canvas.color = Color.BLUE }).apply { setPadding(0, 0, 0, 0) })
        root.addView(buttonRow(compactButton("Undo") { canvas.undo() }, compactButton("Clear") { canvas.clear() }, compactButton("Mark up a photo") { pickPhoto.launch("image/*") })
            .apply { setPadding(0, dp(8), 0, 0) })
        root.addView(canvas, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f).apply { topMargin = dp(8) })
        frame.dockActions(button("Send to computer", true) { send() })
    }
    private fun send() {
        if (canvas.empty()) { Toast.makeText(this, "Draw something first.", Toast.LENGTH_SHORT).show(); return }
        val image = canvas.render()
        lifecycleScope.launch {
            val computers = withContext(Dispatchers.IO) { runCatching { OrionComputers.devices(this@OrionSketchActivity) }.getOrDefault(emptyList()) }
                .filter { it.online && it.computer && "files" in it.capabilities }
            when {
                computers.isEmpty() -> Toast.makeText(this@OrionSketchActivity, "Your paired computers are offline. Nothing was sent.", Toast.LENGTH_LONG).show()
                computers.size == 1 -> deliver(image, computers.single())
                else -> AlertDialog.Builder(this@OrionSketchActivity).setTitle("Send to which computer?")
                    .setItems(computers.map { it.name }.toTypedArray()) { _, index -> deliver(image, computers[index]) }
                    .setNegativeButton("Cancel", null).show()
            }
        }
    }
    private fun deliver(image: Bitmap, computer: LinkDevice) = lifecycleScope.launch {
        val file = File(cacheDir, "orion-sketch-" + UUID.randomUUID() + ".png")
        val ok = withContext(Dispatchers.IO) { runCatching { file.outputStream().use { image.compress(Bitmap.CompressFormat.PNG, 100, it) } }.isSuccess } &&
            files.capture(file, computer.id, "Sketch", "image/png")
        if (!ok) file.delete()
        Toast.makeText(this@OrionSketchActivity, if (ok) "Sent. Paste it on ${computer.name}." else "The sketch could not be sent.", Toast.LENGTH_LONG).show()
        if (ok) finish()
    }
}

/** Freehand strokes over an optional picture. */
class SketchView(context: Context) : View(context) {
    private class Stroke(val path: Path, val paint: Paint)
    private val strokes = mutableListOf<Stroke>()
    private var picture: Bitmap? = null
    var color = Color.BLACK
    init { setBackgroundColor(Color.WHITE) }
    fun background(bitmap: Bitmap) { picture = bitmap; invalidate() }
    fun undo() { strokes.removeLastOrNull(); invalidate() }
    fun clear() { strokes.clear(); picture = null; invalidate() }
    fun empty() = strokes.isEmpty() && picture == null
    private fun pictureBounds(width: Int, height: Int): RectF? = picture?.let { bitmap ->
        val scale = minOf(width.toFloat() / bitmap.width, height.toFloat() / bitmap.height)
        val w = bitmap.width * scale; val h = bitmap.height * scale
        RectF((width - w) / 2, (height - h) / 2, (width + w) / 2, (height + h) / 2)
    }
    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        picture?.let { canvas.drawBitmap(it, null, pictureBounds(width, height)!!, null) }
        strokes.forEach { canvas.drawPath(it.path, it.paint) }
    }
    override fun onTouchEvent(event: MotionEvent): Boolean {
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> strokes += Stroke(Path().apply { moveTo(event.x, event.y) }, Paint(Paint.ANTI_ALIAS_FLAG).apply {
                style = Paint.Style.STROKE; strokeWidth = 8f * resources.displayMetrics.density / 2; strokeCap = Paint.Cap.ROUND; strokeJoin = Paint.Join.ROUND; this.color = this@SketchView.color })
            MotionEvent.ACTION_MOVE -> strokes.lastOrNull()?.path?.lineTo(event.x, event.y)
            else -> return true
        }
        invalidate(); return true
    }
    /** The visible drawing as an image, cropped to the picture when marking one up. */
    fun render(): Bitmap {
        val full = Bitmap.createBitmap(width.coerceAtLeast(1), height.coerceAtLeast(1), Bitmap.Config.ARGB_8888)
        val target = Canvas(full); target.drawColor(Color.WHITE); this.draw(target)
        val crop = pictureBounds(width, height) ?: return full
        val x = crop.left.toInt().coerceIn(0, full.width - 1); val y = crop.top.toInt().coerceIn(0, full.height - 1)
        return Bitmap.createBitmap(full, x, y, crop.width().toInt().coerceIn(1, full.width - x), crop.height().toInt().coerceIn(1, full.height - y))
    }
}
