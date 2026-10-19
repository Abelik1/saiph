// SPDX-License-Identifier: GPL-3.0-only
package com.orionmini.mobile

import android.content.Context
import android.content.res.ColorStateList
import android.graphics.drawable.RippleDrawable
import android.text.Editable
import android.text.InputType
import android.text.TextUtils
import android.text.TextWatcher
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.inputmethod.EditorInfo
import android.widget.Button
import android.widget.EditText
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.Switch
import com.orionmini.mobile.SettingsCatalog.Category

/**
 * Settings in three levels, as on the desktop: a search field and a list of category rows;
 * each category opens its own page; a page holds titled items with compact controls (a
 * switch for on/off, a link row for another screen, a small button for an action). Titles
 * always outrank controls, so a page never becomes a wall of equal, full-width buttons.
 */
object SettingsIcons {
    fun of(category: Category): Int = when (category) {
        Category.ACCOUNT -> sefirah.common.R.drawable.ic_mobile_fill
        Category.CONNECTION -> sefirah.common.R.drawable.ic_sync
        Category.NOTIFICATIONS -> sefirah.common.R.drawable.ic_notifications
        Category.MESSAGES -> sefirah.common.R.drawable.ic_chat
        Category.PHOTOS -> com.castle.sefirah.R.drawable.saiph_ic_photo
        Category.CLIPBOARD -> sefirah.common.R.drawable.ic_content_paste
        Category.CAMERA -> sefirah.common.R.drawable.ic_videocam
        Category.STATUS -> sefirah.common.R.drawable.ic_battery
        Category.PRIVACY -> sefirah.common.R.drawable.ic_lock
        Category.ABOUT -> sefirah.common.R.drawable.ic_info_fill
    }
}

private fun Context.rowTouch(view: View) {
    view.isClickable = true; view.isFocusable = true
    view.background = RippleDrawable(ColorStateList.valueOf(0x33FFFFFF), null, outline(0xFFFFFFFF.toInt(), 0, 12))
}

private fun Context.iconTile(icon: Int) = ImageView(this).apply {
    setImageResource(icon); imageTintList = ColorStateList.valueOf(Palette.ON_TONAL)
    background = outline(Palette.TONAL, Palette.TONAL_LINE, 10); setPadding(dp(7), dp(7), dp(7), dp(7))
    importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
}

/**
 * One row in a settings list: icon, title, a one-line summary, then a chevron (it opens a
 * page) or an outward arrow (it opens Android settings or a web page). The whole row is the
 * touch target and is announced as a button with its title and summary.
 */
fun Context.settingsRow(icon: Int?, title: String, summary: String?, external: Boolean = false, run: () -> Unit): LinearLayout =
    LinearLayout(this).apply {
        orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
        minimumHeight = dp(56); setPadding(dp(4), dp(10), dp(4), dp(10))
        rowTouch(this)
        contentDescription = listOfNotNull(title, summary?.takeIf { it.isNotBlank() }).joinToString(". ")
        androidx.core.view.ViewCompat.setAccessibilityDelegate(this, object : androidx.core.view.AccessibilityDelegateCompat() {
            override fun onInitializeAccessibilityNodeInfo(host: View, info: androidx.core.view.accessibility.AccessibilityNodeInfoCompat) {
                super.onInitializeAccessibilityNodeInfo(host, info); info.className = Button::class.java.name
            }
        })
        if (icon != null) addView(iconTile(icon), LinearLayout.LayoutParams(dp(36), dp(36)).apply { marginEnd = dp(14) })
        addView(LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS
            addView(text(title, UiType.BODY, bold = true))
            if (!summary.isNullOrBlank()) addView(text(summary, UiType.META, Palette.MUTED).apply {
                maxLines = 2; ellipsize = TextUtils.TruncateAt.END; setPadding(0, dp(2), 0, 0)
            })
        }, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        addView(ImageView(context).apply {
            if (external) setImageResource(sefirah.common.R.drawable.ic_open_in_new)
            else { setImageResource(com.castle.sefirah.R.drawable.saiph_ic_chevron_down); rotation = -90f }
            imageTintList = ColorStateList.valueOf(Palette.MUTED)
            importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
        }, LinearLayout.LayoutParams(dp(20), dp(20)).apply { marginStart = dp(8) })
        setOnClickListener { run() }
    }

/** Rows on one card, separated by hairlines. */
fun Context.settingsList(rows: List<View>): LinearLayout = card().apply {
    setPadding(dp(12), dp(6), dp(12), dp(6))
    rows.forEachIndexed { index, row ->
        if (index > 0) addView(View(context).apply { setBackgroundColor(Palette.LINE) },
            LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(1)).apply { marginStart = dp(54) })
        addView(row)
    }
}

/** A quiet, content-width action for a settings item; still a 48 dp target. */
fun Context.compactButton(label: String, tone: Tone = Tone.TONAL, run: () -> Unit) = button(label, tone = tone, run = run).apply {
    minHeight = dp(48); minimumHeight = dp(48); setPadding(dp(16), dp(6), dp(16), dp(6))
}

/** Compact actions in a wrapping row, left-aligned under their item; they stack when they do not fit. */
fun Context.compactActions(vararg buttons: Button): LinearLayout = LinearLayout(this).apply {
    orientation = LinearLayout.VERTICAL; setPadding(0, dp(10), 0, 0)
    buttons.forEachIndexed { index, button ->
        addView(button, LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { if (index > 0) topMargin = dp(8) })
    }
}

/** A setting's switch: bold title on the left, the switch on the right, its explanation below. */
fun Context.settingSwitch(title: String, detail: String?, checked: Boolean, changed: (Switch, Boolean) -> Unit): LinearLayout =
    LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        val toggle = Switch(context).saiph().apply {
            text = title; isChecked = checked; typeface = android.graphics.Typeface.create("sans-serif", android.graphics.Typeface.BOLD)
            setOnCheckedChangeListener { view, on -> changed(view as Switch, on) }
        }
        addView(toggle, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        if (!detail.isNullOrBlank()) addView(text(detail, UiType.META, Palette.MUTED).apply { setPadding(0, 0, dp(56), dp(4)) })
    }

/** The search field at the top of Settings. */
fun Context.settingsSearch(value: String, changed: (String) -> Unit): EditText = field("Search settings").apply {
    setText(value); setSelection(value.length)
    contentDescription = "Search settings"; isSingleLine = true
    inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS; imeOptions = EditorInfo.IME_ACTION_SEARCH
    setCompoundDrawablesRelativeWithIntrinsicBounds(sefirah.common.R.drawable.ic_search, 0, 0, 0)
    androidx.core.widget.TextViewCompat.setCompoundDrawableTintList(this, ColorStateList.valueOf(Palette.MUTED)); compoundDrawablePadding = dp(10)
    background = outline(Palette.FIELD, Palette.LINE_STRONG, 999); setPadding(dp(16), dp(12), dp(16), dp(12))
    (layoutParams as LinearLayout.LayoutParams).bottomMargin = dp(14)
    addTextChangedListener(object : TextWatcher {
        override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
        override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
        override fun afterTextChanged(s: Editable?) { changed(s?.toString().orEmpty()) }
    })
    setOnEditorActionListener { view, action, _ ->
        if (action == EditorInfo.IME_ACTION_SEARCH) {
            context.getSystemService(android.view.inputmethod.InputMethodManager::class.java)?.hideSoftInputFromWindow(view.windowToken, 0); true
        } else false
    }
}

/**
 * The Settings home: search, then one row per category. Typing replaces the category rows with
 * matching items in place (the field keeps focus); choosing one opens its page at that item.
 */
fun Context.settingsHome(entries: List<SettingsCatalog.Entry>, query: String, queryChanged: (String) -> Unit,
                         openCategory: (Category) -> Unit, openEntry: (SettingsCatalog.Entry) -> Unit): LinearLayout =
    LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        val categories = settingsList(SettingsCatalog.categories(entries).map { category ->
            settingsRow(SettingsIcons.of(category), category.title, SettingsCatalog.summary(entries, category)) { openCategory(category) }
        })
        val results = LinearLayout(context).apply { orientation = LinearLayout.VERTICAL }
        fun show(value: String) {
            results.removeAllViews()
            val searching = value.isNotBlank()
            categories.visibility = if (searching) View.GONE else View.VISIBLE
            if (!searching) return
            val found = SettingsCatalog.search(value, entries)
            if (found.isEmpty()) results.addView(body("No settings match “${value.trim()}”.").apply {
                setPadding(dp(4), dp(8), dp(4), dp(8)); accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
            })
            else results.addView(settingsList(found.map { entry ->
                settingsRow(SettingsIcons.of(entry.category), entry.title, entry.category.title) { openEntry(entry) }
            }))
        }
        addView(settingsSearch(query) { queryChanged(it); show(it) })
        addView(results); addView(categories)
        show(query)
    }

/**
 * One category page. Each [item] is a titled block on the page's card; [section] starts a new
 * card under a heading when a page has distinct groups. Items carry their catalog id so a
 * search result can [reveal] them.
 */
class SettingsPage(private val root: LinearLayout, private val entries: List<SettingsCatalog.Entry>) {
    private val context: Context = root.context
    private val items = mutableMapOf<String, View>()
    private var card: LinearLayout? = null

    fun section(title: String) {
        root.addView(context.section(title)); card = null
    }

    /** A titled item. [detail] is one or two sentences; [build] adds its compact controls. */
    fun item(id: String, detail: String? = null, title: String = titleOf(id), build: LinearLayout.() -> Unit = {}): LinearLayout {
        val holder = card ?: context.card().also { root.addView(it); card = it }
        if (holder.childCount > 0) holder.addView(context.divider())
        val block = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            addView(context.text(title, UiType.BODY, bold = true).apply { androidx.core.view.ViewCompat.setAccessibilityHeading(this, true) })
            if (!detail.isNullOrBlank()) addView(context.text(detail, UiType.META, Palette.MUTED).apply { setPadding(0, context.dp(4), 0, 0) })
            build()
        }
        holder.addView(block); items[id] = block
        return block
    }

    /** An on/off item: its switch on the title line; [build] may add a compact action below. */
    fun switchItem(id: String, detail: String?, checked: Boolean, title: String = titleOf(id), build: LinearLayout.() -> Unit = {},
                   changed: (Switch, Boolean) -> Unit): View {
        val holder = card ?: context.card().also { root.addView(it); card = it }
        if (holder.childCount > 0) holder.addView(context.divider())
        return context.settingSwitch(title, detail, checked, changed).apply(build).also { holder.addView(it); items[id] = it }
    }

    /** An item that opens another screen or Android's own settings. */
    fun linkItem(id: String, summary: String?, external: Boolean = false, title: String = titleOf(id), run: () -> Unit): View {
        val holder = card ?: context.card().also { root.addView(it); card = it }
        if (holder.childCount > 0) holder.addView(context.divider())
        return context.settingsRow(null, title, summary, external, run).apply { setPadding(0, dp(6), 0, dp(6)) }
            .also { holder.addView(it); items[id] = it }
    }

    private fun titleOf(id: String) = entries.firstOrNull { it.id == id }?.title ?: id
    private fun View.dp(value: Int) = context.dp(value)

    /** Scroll a searched item into view and mark it briefly, so the jump is easy to follow. */
    fun reveal(id: String, scroll: ScrollView) {
        val target = items[id] ?: return
        target.post {
            var top = 0; var view: View? = target
            while (view != null && view !== scroll) { top += view.top; view = view.parent as? View }
            scroll.smoothScrollTo(0, (top - context.dp(24)).coerceAtLeast(0))
            val previous = target.background
            target.background = context.outline(Palette.TONAL, Palette.TONAL_LINE, 12)
            target.postDelayed({ target.background = previous }, 1600)
            target.sendAccessibilityEvent(android.view.accessibility.AccessibilityEvent.TYPE_VIEW_FOCUSED)
        }
    }
}
