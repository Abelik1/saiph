# Integrated phone camera

The Windows desktop build includes its camera component. Users install Saiph on
their computer and phone; they do not install or configure OBS, Unity, scrcpy or
another camera app for this path.

1. Connect the phone and computer to the same Wi-Fi or private LAN.
2. On the computer, choose Phone → Webcam, select resolution, target frame rate
   and image quality, then choose Use phone as webcam.
3. A phone connected with Saiph Cloud shows the notification "Start camera for
   <computer>?"; tap it. Otherwise, on Android choose Use phone as webcam → Scan
   computer's camera code. The QR stays on the computer's screen as a fallback.
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

The camera uses private IPv4 networks. Desktop buttons select 720p or 1080p,
15, 20 or 30 fps, and Standard or High detail JPEG quality. New desktop sessions
default to 1080p, 20 fps and High detail. Settings apply to the next session;
stop and start again to change them. Both apps need the updated camera protocol.
Older desktop invitations remain supported at 720p/15 fps on the updated phone.
Actual capture resolution depends on the camera's supported modes. The live
desktop reports the received source dimensions and rolling received frame rate,
separately from the selected target, and the rate the preview actually shows.
The preview is the phone's own JPEG: the desktop decodes each frame once to
validate it, then hands the unchanged bytes to the dashboard through its local
frame feed, where Chromium decodes and rotates it (see
[DESKTOP_PERFORMANCE.md](DESKTOP_PERFORMANCE.md)); the virtual-camera producer
retains the selected 1280×720 or 1920×1080 output. Select 1080p in the meeting app as well to receive that output
without its own downscaling. Portrait video is fitted within the landscape output.
Higher settings consume more Wi-Fi bandwidth and phone power. They are targets,
not a guarantee of sustained physical capture performance.
Internet relay, NAT traversal, USB-only transport and guaranteed performance on
physical phones are not implemented. The preview works on desktop platforms;
the bundled meeting-app camera is Windows-specific. Legacy USB/debugging tools
remain under Settings → Devices → Legacy USB camera tools (advanced), preserving
existing settings and internal Orion/OBS identifiers.

## Protocol and local trust

This optional session is independent of device pairing. It does not add a roster
member, change trust keys or transmit camera video through the Hub. Scanning the
camera QR grants this one session to the computer whose screen the owner
deliberately scanned. It is a private capability and must not be shared or
screen-shared.

Instead of a scan, the computer may send the same invitation to one approved,
online Saiph Cloud phone as a sealed `session.offer` (see
[QRLESS_CONNECT.md](QRLESS_CONNECT.md)). Only that phone's keys can open it; the
relay sees ciphertext. The phone accepts it only from a current subscribed
computer, shows it once and keeps it in memory, and its notification and intent
carry only an offer ID. Tapping still requires owner verification, Android camera
access and the foreground. The offer expires with the invitation, and the desktop
erases the bearer secret on first use, so a replay gets nothing.

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
message is 1,500,000 bytes, maximum dimension 1920 and maximum pixel count 2,073,600.
Version 2 invitations bind an exact, bounded stream profile to the one-use QR;
version 1 invitations retain the 720p pixel limit. Unsupported profiles are refused.
JPEG dimensions are checked before decoding; rotation and sequences are bounded.
The receive queue retains one frame; a 60 fps decode-work ceiling allows jitter
in the phone's selected 15/20/30 fps cadence. Android keeps only the latest camera
frame and skips encoding while its socket has queued data. YUV planes are packed
directly for JPEG, avoiding a per-frame RGB conversion in the normal capture path.
The desktop decodes and scales outside its preview/state lock and discards results
if the session stopped or was replaced meanwhile. Idle
or interrupted peers time out after eight seconds. No audio messages exist.
Invitations and image bytes are excluded from status and application diagnostics.

On an installed Windows Saiph the session listens on 127.0.0.1 behind the
fixed-path relay `SaiphNetwork.exe`, so the owner's Windows Firewall answer keeps
applying after updates ([LAN_FILES.md](LAN_FILES.md#windows-firewall-across-updates)).
The phone screen uses the same listener.

## Bundled Windows component

`native/camera/` retains the pinned UnityCapture filter source, copyright headers,
MIT notice and explicit Saiph build-time adaptations. Source and component hashes
are recorded in camera-build.json. Both x64 and x86 DLLs are packaged. They use
Saiph-specific CLSIDs and an independent IPC namespace, leaving other virtual
cameras intact. First use registers only Saiph's per-user classes. Installer
upgrade/uninstall cleanup requires package-hash proof of ownership; foreign
registrations are preserved. If a registration from another release folder of the
same installation (`<root>\releases\<version>\app\_internal\camera\`, same file
name) is still present, first use replaces it; any other existing registration,
including one from a different install root or a source build, is still refused.
Stopping blanks the producer before reporting idle;
the filter also blanks stale frames. The normal UI contains no third-party setup.

## Verification and limits

Use isolated profiles and the desktop control tools in [TESTING.md](TESTING.md).
Run the Python camera/session/origin/installer suite and frontend interaction
tests. Their threaded websockets client uses TLS 1.2 and a separate sequential client
checks TLS 1.3; [PHONE_SCREEN.md](PHONE_SCREEN.md#verification) explains the TLS 1.3
stall that CPython's concurrent client caused (the server is unaffected). Build both Windows component architectures using native/camera/build.py,
then run each SaiphCameraTest.exe against its matching DLL, both with no extra
argument (720p) and with `1080p` (1080p/20 fps negotiation). Registration in these
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
