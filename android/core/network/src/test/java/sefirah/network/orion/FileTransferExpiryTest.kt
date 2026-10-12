package sefirah.network.orion

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class FileTransferExpiryTest {
    private fun event(created: Double, expires: Double = created + 300) = buildJsonObject {
        put("created_at",created);put("expires_at",expires);put("id","test-event")
    }
    @Test fun anOfflineTransferRetriesWithinTheOfferLifetimeThenExpires() {
        val metadata=event(100.0)
        assertFalse(FileTransferExpiry.expired(metadata,101.0))
        assertFalse(FileTransferExpiry.expired(metadata,401.0)) // Bus TTL already passed; blob is still valid.
        assertFalse(FileTransferExpiry.expired(metadata,999.99))
        assertTrue(FileTransferExpiry.expired(metadata,1000.0))
    }
    @Test fun abandonedQueueReleasesCapacityWithoutRemovingCompletionReceipts() {
        val persisted=mutableMapOf<String,Any>()
        repeat(20) { persisted["pending:$it"]=event(100.0).toString() }
        persisted["done:completed"]=500L
        persisted["uri:partial"]="content://downloads/synthetic"
        assertEquals(20,persisted.keys.count { it.startsWith("pending:") })
        FileTransferExpiry.pending(persisted,1000.0).forEach { persisted.remove("pending:$it") }
        persisted["pending:new"]=event(1000.0).toString()
        assertEquals(1,persisted.keys.count { it.startsWith("pending:") })
        assertEquals(500L,persisted["done:completed"])
        assertTrue(FileTransferExpiry.pending(persisted,1001.0).isEmpty())
    }
    @Test fun corruptOrImpossiblePersistedMetadataCannotHoldAQueueSlotForever() {
        val entries=mapOf("pending:invalid" to "bad-json","pending:missing" to "{}",
            "pending:future" to event(2000.0).toString(),"pending:negative" to event(-100.0).toString(),
            "pending:valid" to event(900.0).toString(),"done:valid" to 1000L)
        assertEquals(setOf("invalid","missing","future","negative"),FileTransferExpiry.pending(entries,1000.0).toSet())
    }
}
