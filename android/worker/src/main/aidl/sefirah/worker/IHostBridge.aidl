package sefirah.worker;

import android.os.ParcelFileDescriptor;

interface IHostBridge {
    void onClipboardText(String text) = 1;

    void onClipboardImage(String mimeType, in ParcelFileDescriptor fd) = 2;
}
