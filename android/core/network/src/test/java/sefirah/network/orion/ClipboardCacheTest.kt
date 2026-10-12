package sefirah.network.orion
import org.junit.Assert.*
import org.junit.Test

class ClipboardCacheTest {
    @Test fun remoteWritesAndClassificationCallbacksDoNotRebroadcast() {
        var clock=0L
        val cache=ClipboardCache { clock }
        val hash=ClipboardCache.hash("Synthetic clipboard".toByteArray())
        assertTrue(cache.claim("text/plain",hash))
        assertFalse(cache.claim("text/plain",hash))
        clock=9_999
        assertFalse(cache.claim("text/plain",hash))
        clock=300_001
        assertTrue(cache.claim("text/plain",hash))
    }
    @Test fun repeatedContentAfterAnotherCopyIsDeliveredAgain() {
        // Physical acceptance: a reused image fixture never reached the phone because
        // any value seen in the previous five minutes was suppressed.
        var clock=0L
        val cache=ClipboardCache { clock }
        val a=ClipboardCache.hash("A".toByteArray());val b=ClipboardCache.hash("B".toByteArray())
        for(value in listOf(a,b,a,b,a)) {
            clock+=1_000
            assertTrue(cache.claim("image/png",value))
            assertFalse(cache.claim("image/png",value))
        }
    }
    @Test fun differentMimeIsIndependent() {
        val cache=ClipboardCache { 0L }
        val hash=ClipboardCache.hash(byteArrayOf(1,44))
        assertTrue(cache.claim("image/png",hash))
        assertFalse(cache.claim("image/png",hash))
        assertTrue(cache.claim("image/jpeg",hash))
    }
}
