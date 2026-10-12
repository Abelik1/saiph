package com.orionmini.mobile

import com.castle.sefirah.BuildConfig
import org.junit.Assert.*
import org.junit.Test
import sefirah.network.orion.MeshOrigin

class BuildVariantTest {
    @Test fun independentDistributionNeverUsesOwnerHubDefault() {
        assertEquals("com.orionmini.mobile", BuildConfig.APPLICATION_ID)
        assertEquals("0.8.7", BuildConfig.VERSION_NAME)
        if (BuildConfig.INDEPENDENT) {
            // Push is an explicit opt-in that needs Firebase; it is never implied by it.
            assertTrue(!BuildConfig.HAS_FIREBASE_PUSH || BuildConfig.HAS_FIREBASE)
            assertEquals("", MeshOrigin.DEFAULT)
            assertTrue(runCatching { MeshOrigin.validate("http://legacy.example.invalid:8765") }.isFailure)
        } else {
            assertEquals("", MeshOrigin.DEFAULT)
        }
        assertEquals("http://100.100.10.2:12345", MeshOrigin.validate("http://100.100.10.2:12345"))
    }

    @Test fun appDistributionSelfUpdateOnlyInPreReleaseBuildTypes() {
        assertTrue(!BuildConfig.HAS_APP_DISTRIBUTION || BuildConfig.HAS_FIREBASE)
        if (BuildConfig.BUILD_TYPE == "release") assertFalse(BuildConfig.HAS_APP_DISTRIBUTION)
        if (BuildConfig.BUILD_TYPE == "beta") assertFalse(BuildConfig.DEBUG)
    }

    @Test fun pairedOwnerAndFriendNumericOriginsSurviveNeutralUpgrade() {
        listOf("http://100.64.0.2:8765", "http://100.100.10.2:12345").forEach { saved ->
            repeat(20) { assertEquals(saved, MeshOrigin.validate(saved)) }
        }
        if (BuildConfig.INDEPENDENT) {
            assertTrue(runCatching { MeshOrigin.validate("") }.isFailure)
            assertTrue(runCatching { MeshOrigin.validate("http://legacy.example.invalid:8765") }.isFailure)
        }
    }
}
