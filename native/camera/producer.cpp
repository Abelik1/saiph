// SPDX-License-Identifier: AGPL-3.0-or-later
#include "shared.inl"
#include <mutex>

static std::mutex guard;
static SharedImageMemory* sender = nullptr;
static unsigned int lastWidth = 1280, lastHeight = 720;
extern "C" __declspec(dllexport) int SaiphCameraWriteSized(const unsigned char* rgba, unsigned int size,
    unsigned int width, unsigned int height) {
    if (!rgba || !((width == 1280 && height == 720) || (width == 1920 && height == 1080))
        || size != width * height * 4u) return -1;
    std::lock_guard<std::mutex> lock(guard);
    lastWidth = width; lastHeight = height;
    if (!sender) sender = new SharedImageMemory(0);
    if (!sender->SendIsReady()) return 0; // No receiving meeting app yet.
    return sender->Send(width, height, width, size, SharedImageMemory::FORMAT_UINT8,
        SharedImageMemory::RESIZEMODE_LINEAR, SharedImageMemory::MIRRORMODE_DISABLED, 500, rgba) + 1;
}
extern "C" __declspec(dllexport) int SaiphCameraWrite(const unsigned char* rgba, unsigned int size) {
    return SaiphCameraWriteSized(rgba, size, 1280, 720);
}
extern "C" __declspec(dllexport) void SaiphCameraStop() {
    std::lock_guard<std::mutex> lock(guard);
    if (sender && sender->SendIsReady()) {
        static const unsigned char black[1920u * 1080u * 4u] = {};
        sender->Send(lastWidth, lastHeight, lastWidth, lastWidth * lastHeight * 4u, SharedImageMemory::FORMAT_UINT8,
            SharedImageMemory::RESIZEMODE_LINEAR, SharedImageMemory::MIRRORMODE_DISABLED, 1, black);
    }
    delete sender; sender = nullptr;
}
