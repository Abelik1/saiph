// SPDX-License-Identifier: AGPL-3.0-or-later
#include "shared.inl"
#include <mutex>

static std::mutex guard;
static SharedImageMemory* sender = nullptr;
extern "C" __declspec(dllexport) int SaiphCameraWrite(const unsigned char* rgba, unsigned int size) {
    if (!rgba || size != 1280u * 720u * 4u) return -1;
    std::lock_guard<std::mutex> lock(guard);
    if (!sender) sender = new SharedImageMemory(0);
    if (!sender->SendIsReady()) return 0; // No receiving meeting app yet.
    return sender->Send(1280, 720, 1280, size, SharedImageMemory::FORMAT_UINT8,
        SharedImageMemory::RESIZEMODE_LINEAR, SharedImageMemory::MIRRORMODE_DISABLED, 500, rgba) + 1;
}
extern "C" __declspec(dllexport) void SaiphCameraStop() {
    std::lock_guard<std::mutex> lock(guard);
    if (sender && sender->SendIsReady()) {
        static const unsigned char black[1280u * 720u * 4u] = {};
        sender->Send(1280, 720, 1280, sizeof(black), SharedImageMemory::FORMAT_UINT8,
            SharedImageMemory::RESIZEMODE_LINEAR, SharedImageMemory::MIRRORMODE_DISABLED, 1, black);
    }
    delete sender; sender = nullptr;
}
