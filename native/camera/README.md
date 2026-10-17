# Saiph Camera component

The Windows component is built into Saiph; users do not install OBS, Unity or a
camera helper app. The capture filter is derived from UnityCapture at immutable
commit `3ed54c325e0ad71afcf4f246c07e5e17b3d7f2d2`:
https://github.com/schellingb/UnityCapture/tree/3ed54c325e0ad71afcf4f246c07e5e17b3d7f2d2/Source

`upstream/` retains original source and copyright headers. UnityCapture identifies
its filter as MIT licensed. Its combined DirectShow base classes retain their
Microsoft copyright headers. `LICENSE.UnityCapture.txt` retains the filter's
copyright and licence. These files are separate from the MIT SDK.

`build.py` verifies canonical upstream hashes before making explicit build-time
changes: a separate Saiph name, CLSIDs and IPC namespace; one camera; bounded 720p
RGBA frames; blank output when stopped; mutex rights and invalid-header checks.
The original Unity/OBS camera registrations are not used or modified.

`registration.cpp` registers only Saiph's own DirectShow COM classes and device
category instance in the current user's registry. First use handles registration;
no third-party installer or administrative registry edits are required. It refuses
foreign registrations. Unregistration requires the exact registered module path.
Native registration and meeting-app compatibility still require acceptance on a
disposable Windows installation; in-process tests do not establish those results.

Build with Python 3.12, CMake and Visual Studio C++ tools:

    python native/camera/build.py --output build/camera-native

Both x64 and x86 filters are retained with a source/hash receipt and licence. The
desktop uses the x64 producer. Receiving applications load their matching filter.
No camera registration occurs during compilation or ordinary unit tests.
