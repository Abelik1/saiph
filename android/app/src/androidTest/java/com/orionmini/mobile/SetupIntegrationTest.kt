package com.orionmini.mobile

import android.content.Context
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.TextView
import android.widget.ScrollView
import androidx.lifecycle.Lifecycle
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.espresso.Espresso.onView
import androidx.test.espresso.assertion.ViewAssertions.matches
import androidx.test.espresso.action.ViewActions.click
import androidx.test.espresso.action.ViewActions.scrollTo
import androidx.test.espresso.action.ViewActions.swipeUp
import androidx.test.espresso.matcher.ViewMatchers.isDisplayed
import androidx.test.espresso.matcher.ViewMatchers.withText
import androidx.test.espresso.matcher.ViewMatchers.withParent
import androidx.test.espresso.matcher.ViewMatchers.hasDescendant
import androidx.test.espresso.matcher.ViewMatchers.isAssignableFrom
import org.hamcrest.Matchers.allOf
import org.hamcrest.Matchers.equalToIgnoringCase
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class SetupIntegrationTest {
    private fun views(view: View): List<View> = listOf(view) + if (view is ViewGroup)
        (0 until view.childCount).flatMap { views(view.getChildAt(it)) } else emptyList()
    private fun buttons(activity: OrionActivity) = views(activity.window.decorView).filterIsInstance<Button>()
    /** Settings is the header's gear, an icon button named by its spoken label. */
    private fun settingsButton(activity: OrionActivity) = views(activity.window.decorView).single { it.contentDescription == "Settings" }

    @Test fun pairedPhoneCanFinishOfflineWithoutFuturePermissionsOrVpnCheckbox() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val prefs = context.getSharedPreferences("orion", Context.MODE_PRIVATE)
        assumeTrue(prefs.contains("device_id"))
        val previous = prefs.getBoolean("setup_done", false)
        val vpn = prefs.getBoolean("vpn_confirmed", false)
        prefs.edit().putBoolean("setup_done", false).putBoolean("vpn_confirmed", false).commit()
        try {
            ActivityScenario.launch(OrionActivity::class.java).use { scenario ->
                scenario.onActivity { activity ->
                    assertFalse(buttons(activity).any { it.text == "I've set the VPN options" })
                    val state = activity.link.status.value
                    try {
                        activity.link.status.value = "Reconnecting"
                        buttons(activity).single { it.text == "Finish setup" }.performClick()
                        assertTrue(prefs.getBoolean("setup_done", false))
                        assertTrue(views(activity.window.decorView).any { it.contentDescription == "Settings" })
                        assertFalse(buttons(activity).any { it.text == "Finish setup" })
                    } finally { activity.link.status.value = state }
                }
                // Returning to the activity must not undo the completed setup.
                scenario.moveToState(Lifecycle.State.CREATED).moveToState(Lifecycle.State.RESUMED)
                scenario.onActivity { activity -> assertFalse(buttons(activity).any { it.text == "Finish setup" }) }
            }
        } finally { prefs.edit().putBoolean("setup_done", previous).putBoolean("vpn_confirmed", vpn).commit() }
    }

    @Test fun bundledWorkerHelpDoesNotBlockSetup() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val prefs = context.getSharedPreferences("orion", Context.MODE_PRIVATE)
        assumeTrue(prefs.contains("device_id"))
        val previous = prefs.getBoolean("setup_done", false)
        prefs.edit().putBoolean("setup_done", false).commit()
        try {
            ActivityScenario.launch(OrionActivity::class.java).use { scenario ->
                // Exercise a real visible tap. Programmatic clicks on an offscreen card
                // do not reproduce Samsung's window/focus behavior.
                // Espresso's scrollTo fails for the last padded card on this long
                // page; real swipes reach it, including with optional photo/Focus cards.
                onView(isAssignableFrom(ScrollView::class.java)).perform(swipeUp(), swipeUp(), swipeUp())
                onView(allOf(withText("Set up"), withParent(withParent(
                    hasDescendant(withText("Background clipboard"))))))
                    .perform(click())
                onView(withText("Background clipboard")).check(matches(isDisplayed()))
                // Close the optional dialog and ensure setup remains finishable.
                onView(withText(equalToIgnoringCase("Later"))).perform(click())
                scenario.onActivity { activity -> assertTrue(buttons(activity).single { it.text == "Finish setup" }.isEnabled) }
            }
        } finally { prefs.edit().putBoolean("setup_done", previous).commit() }
    }

    @Test fun returningFromConnectionSettingsKeepsAdvancedOpen() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val prefs = context.getSharedPreferences("orion", Context.MODE_PRIVATE)
        assumeTrue(prefs.contains("device_id"))
        val previous = prefs.getBoolean("setup_done", false)
        prefs.edit().putBoolean("setup_done", true).commit()
        try {
            ActivityScenario.launch(OrionActivity::class.java).use { scenario ->
                scenario.onActivity { activity ->
                    settingsButton(activity).performClick()
                    buttons(activity).single { it.text == "Advanced" }.performClick()
                }
                scenario.moveToState(Lifecycle.State.CREATED).moveToState(Lifecycle.State.RESUMED)
                scenario.onActivity { activity -> assertTrue(buttons(activity).any { it.text == "VPN settings" }) }
            }
        } finally { prefs.edit().putBoolean("setup_done", previous).commit() }
    }
}
