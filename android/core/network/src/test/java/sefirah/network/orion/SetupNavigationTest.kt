package sefirah.network.orion

import org.junit.Assert.*
import org.junit.Test

class SetupNavigationTest {
    @Test fun initialPairingShowsSetupButReturningFromPermissionSettingsKeepsBackAvailable() {
        assertEquals("pair", SetupNavigation.resume("home",false,false,false))
        var page=SetupNavigation.resume("home",true,false,false)
        assertEquals("setup",page)
        repeat(5) {
            page=SetupNavigation.resume(page,true,false,false)
            assertEquals("setup",page)
            assertTrue(SetupNavigation.offersBack(page,true))
        }
        assertEquals("home",SetupNavigation.back(page))
    }
    @Test fun deferredSetupSurvivesActivityRecreationWithoutMarkingComplete() {
        // Back stores deferred=true and leaves complete=false; a fresh Activity starts at home.
        val complete=false; val deferred=true
        repeat(5) { assertEquals("home",SetupNavigation.resume("home",true,complete,deferred)) }
        assertFalse(SetupNavigation.notificationOpensSetup(complete,deferred))
        assertEquals("settings",SetupNavigation.resume("home",true,complete,deferred,requestSettings=true))
        assertEquals("setup",SetupNavigation.resume("home",true,complete,deferred,requestSetup=true))
    }
    @Test fun explicitPermissionReviewStaysOpenAfterOsReturnButBackAlwaysLeaves() {
        var page=SetupNavigation.resume("home",true,false,true,requestSetup=true)
        page=SetupNavigation.resume(page,true,false,true)
        assertEquals("setup",page)
        assertTrue(SetupNavigation.offersBack(page,true))
        assertEquals("home",SetupNavigation.back(page))
        assertEquals("settings",SetupNavigation.back("advanced"))
        assertEquals("home",SetupNavigation.back("settings"))
        assertNull(SetupNavigation.back("home"))
    }
    @Test fun finishedSetupDoesNotReopenBecauseOptionalPermissionIsMissing() {
        assertEquals("home",SetupNavigation.resume("home",true,true,false))
        assertFalse(SetupNavigation.notificationOpensSetup(true,false))
        assertFalse(SetupNavigation.notificationOpensSetup(true,true))
        assertTrue(SetupNavigation.notificationOpensSetup(false,false))
        assertEquals("settings",SetupNavigation.resume("home",true,true,false,requestSettings=true))
    }
    @Test fun unpairedDeviceCannotBypassEnrollmentThroughNotificationIntents() {
        assertEquals("pair",SetupNavigation.resume("settings",false,true,true,requestSetup=true,requestSettings=true))
        assertFalse(SetupNavigation.offersBack("pair",false))
    }
}
