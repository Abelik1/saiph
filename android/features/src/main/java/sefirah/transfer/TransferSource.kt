package sefirah.transfer

import sefirah.domain.model.FileMetadata
import java.io.InputStream

class TransferSource(
    val metadata: FileMetadata,
    private val openStream: () -> InputStream,
) {
    fun open(): InputStream = openStream()
}