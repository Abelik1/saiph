package com.orionmini.mobile

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import android.content.ContextWrapper
import android.content.SharedPreferences
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import sefirah.network.orion.CommandReceipts
import java.util.UUID

@RunWith(AndroidJUnit4::class)
class CommandReceiptsTest {
    @Test fun replayDoesNotRepeatAnActionAfterNewHandlerInstance() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val fixture = context.getSharedPreferences("command_receipt_test_" + UUID.randomUUID(), 0)
        val isolated = object : ContextWrapper(context) {
            override fun getSharedPreferences(name: String, mode: Int): SharedPreferences = fixture
        }
        try {
            val id = UUID.randomUUID().toString()
            assertTrue(CommandReceipts(isolated).claim(id))
            assertFalse(CommandReceipts(isolated).claim(id))
            assertTrue(CommandReceipts(isolated).claim(UUID.randomUUID().toString()))
        } finally { fixture.edit().clear().commit() }
    }
}
