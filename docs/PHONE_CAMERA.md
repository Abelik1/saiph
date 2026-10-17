# Integrated phone camera

The Windows desktop build includes its camera component. Users install Saiph on
their computer and phone; they do not install or configure OBS, Unity, scrcpy or
another camera app for this path.

1. Connect the phone and computer to the same Wi-Fi or private LAN.
2. On the computer, choose Phone → Webcam → Use phone as webcam.
3. On Android, choose Use phone as webcam → Scan computer's camera code.
4. Choose the front or rear camera, tap Start camera, verify the phone's owner and
   allow Android camera access. The phone needs a secure screen lock for this grant.
5. Select Saiph Camera in the meeting app. Stop on either device to finish.

Preview camera uses the same phone flow without registering a virtual webcam.
The camera screen stays visible and keeps the phone awake. Leaving it, locking
the phone, closing either app, disconnecting or disabling Phone camera ends the
session. Audio is never captured by this camera path. Video is not recorded;
only the current bounded preview is retained in memory. Sessions expire after
30 minutes and require a new code. Camera permissions never grant photo-library,
SMS or microphone access.

The first implementation uses private IPv4 networks and targets bounded 720p
frames at up to 15 fps. Portrait video is fitted inside a 1280×720 webcam frame.
Internet relay, NAT traversal, USB-only transport and guaranteed performance on
physical phones are not implemented. The preview works on desktop platforms;
the bundled meeting-app camera is Windows-specific. Legacy USB/debugging tools
remain under Settings → Devices → Legacy USB camera tools (advanced), preserving
existing settings and internal Orion/OBS identifiers.

## Protocol and local trust

This optional session is independent of account sign-in and device pairing. It
does not add a roster member, change trust keys, use the Cloud mailbox or transmit
camera video through the Hub. Scanning the camera QR grants this one session to
the computer whose screen the owner deliberately scanned. It is a private
capability and must not be shared or screen-shared.

The desktop generates an ephemeral P-256 TLS certificate, a 256-bit random bearer
capability and a 128-bit random session ID. The invitation contains literal
RFC1918 IPv4 endpoints, the certificate SHA-256 pin and a two-minute deadline.
Android rejects public, loopback, DNS, link-local and ambiguous addresses; checks
the exact certificate and IP hostname; disables proxies/redirects and sends the
capability only inside that pinned TLS connection. The desktop claims the
capability before WebSocket upgrade, accepts one connection and erases it.
Expired codes, second consumers and replayed or nonmonotonic frames are refused.
No accounts, owner infrastructure values or persistent private keys are embedded
in the component or invitation. TLS needs no extra installed application.

Binary frames have an 18-byte network-order SCF1 header: magic, 16-bit width,
16-bit height, 16-bit rotation and 64-bit sequence, followed by JPEG. The maximum
message is 512,000 bytes, maximum dimension 1280 and maximum pixel count 921,600.
JPEG dimensions are checked before decoding; rotation and sequences are bounded.
The receive queue retains one frame and decode rate is bounded at 20 fps. Idle
or interrupted peers time out after eight seconds. No audio messages exist.
Invitations and image bytes are excluded from status and application diagnostics.

## Bundled Windows component

`native/camera/` retains the pinned UnityCapture filter source, copyright headers,
MIT notice and explicit Saiph build-time adaptations. Source and component hashes
are recorded in camera-build.json. Both x64 and x86 DLLs are packaged. They use
Saiph-specific CLSIDs and an independent IPC namespace, leaving other virtual
cameras intact. First use registers only Saiph's per-user classes. Installer
upgrade/uninstall cleanup requires package-hash proof of ownership; foreign
registrations are preserved. Stopping blanks the producer before reporting idle;
the filter also blanks stale frames. The normal UI contains no third-party setup.

## Verification and limits

Use isolated profiles and the desktop control tools in [TESTING.md](TESTING.md).
Run the Python camera/session/origin/installer suite and frontend interaction
tests. Build both Windows component architectures using native/camera/build.py,
then run each SaiphCameraTest.exe against its matching DLL. Registration in these
tests is redirected into a newly owned registry subtree; the tests also run an
actual DirectShow streaming graph with a synthetic renderer. No system camera
is installed on the development PC.

The Android native camera test requires a fresh, explicitly provisioned synthetic
TLS invitation in the disposable app's cache. It rejects a wrong certificate,
checks a permission/verification result received while paused, captures generated
emulator CameraX frames and verifies that leaving the screen releases capture.
It invokes the capture controller directly; it does not claim native owner
verification acceptance. The outer harness clears the disposable profile after
the run, because revoking the app's camera permission kills its own runner.

Passing these checks does not establish physical-phone performance, Windows
installation/upgrade acceptance, global camera enumeration, Zoom/Teams/browser
compatibility, Windows publisher signing or independent security/licensing
review. Those remain separate release acceptance requirements.
