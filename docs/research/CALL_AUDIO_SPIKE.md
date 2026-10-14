# Call audio through the computer (B2): research spike

**Status:** desk research done on 14 October 2026; nothing has been tested on
real hardware yet. Plan item B2 in [PHONE_LINK_PARITY.md](../PHONE_LINK_PARITY.md).
**Recommendation:** Linux: go, as a prototype. Windows: no-go for now, pending
one short check on real hardware. Android: no app change is needed to start.

The website says: "Calls — see who's calling. Answer from your desk." Saiph can
already show incoming calls and answer or decline them (`call.state`,
`call.command`). The call audio stays on the phone or its headset. Phone Link can
also put the conversation through the PC's microphone and speakers. This spike
asks whether Saiph can do the same.

## 1. Why it has to be Bluetooth

Android does not let ordinary apps capture or inject cellular call audio. The
`VOICE_CALL` capture source needs a privileged permission. scrcpy can capture
`voice-call` audio over ADB as the shell user on some devices, but it cannot
feed the computer's microphone into the call. It also needs debugging turned on.
That is not a two-way route.

The only route that works on standard phones is the one car kits and headsets
use: **Bluetooth Hands-Free Profile (HFP)**. The phone is the *Audio Gateway*
(AG). The computer takes the *Hands-Free* (HF) role. Call audio travels over a
Bluetooth SCO/eSCO link, using CVSD or wideband mSBC (and LC3-SWB on newer
stacks). Call control uses AT commands over RFCOMM: `ATA` answers, `AT+CHUP`
hangs up, `ATD` dials, and `+CLCC`/`+CIEV` report call state. Phone Link works
this way too. Microsoft's setup page requires Bluetooth, and its troubleshooting
blames PCs whose adapter lacks HFP.

Whether Saiph can do this therefore depends on whether **the desktop OS lets a
normal, unprivileged app take the HF role and route the SCO audio**.

## 2. Feasibility at a glance

| Platform | HF role available to Saiph? | Call audio | Call control | Root/admin or install needed | Verdict |
| --- | --- | --- | --- | --- | --- |
| Ubuntu 26.04 LTS (PipeWire 1.6.2, WirePlumber 0.5.13, BlueZ 5.85) | Yes. `hfp_hf` is in WirePlumber 0.5's default roles | Handled by PipeWire's native backend (claimed; to be proven on hardware) | `org.pipewire.Telephony` on the **session** bus (PipeWire ≥ 1.4), or Saiph's own app commands | None expected | **Go (prototype)** |
| Ubuntu 24.04 LTS (PipeWire 1.0.5, WirePlumber 0.4.17, BlueZ 5.72) | Off by default (0.4 default roles are `hsp_hs hfp_ag`). One per-user config file turns it on | As above | No HFP API in PipeWire 1.0; use Saiph's existing `call.command` / `call.dial` | No root: user file plus `systemctl --user restart wireplumber` | **Go (prototype)**, with a consented setup step |
| Ubuntu 22.04 LTS (PulseAudio 15.99, BlueZ 5.64) | Only through oFono (`headset=ofono`), a system service | Through PulseAudio + oFono | oFono D-Bus (system bus) | Root: install and configure oFono, or switch the whole session to PipeWire | **No-go** (document the manual path only) |
| Windows 10/11 (tested target: Windows 11 25H2, build 26200) | Only through `PhoneLineTransportDevice`. This needs a restricted capability (package identity) and is gated since 22H2. Phone Link holds the registration | Windows' in-box HF stack can route it for the registered app (Thy Phone shipped this). Community attempts without that registration got no SCO audio | `PhoneLine`/`PhoneLineTransportDevice` WinRT APIs | MSIX or sparse-package identity; possibly a Microsoft Limited Access Feature unlock | **No-go now**, then a 2-day gate test |
| Windows: custom HFP profile driver + audio driver | Technically possible | Kernel audio driver talking to the HFP driver (Microsoft's "HFP bypass" model is for SoC vendors) | Driver | Driver signing (EV certificate, Microsoft attestation) and admin install | **No-go** |
| Windows/Linux: separate user-space stack on a dedicated USB dongle (Google Bumble) | Yes, but it takes the dongle away from the OS | SCO over USB from user space has not been shown on Windows | Bumble HFP | Swap the dongle's driver to WinUSB (admin); Bumble describes itself as alpha | **No-go** for the product (research curiosity only) |

## 3. Windows findings

**How Phone Link does it.** Phone Link pairs the phone over Bluetooth and uses the
Windows in-box Hands-Free stack. It is a separate Bluetooth role that Microsoft's
docs describe through the `Windows.ApplicationModel.Calls` APIs. The OS opens the
SCO audio and exposes it as a call-audio endpoint. Phone Link supplies the call
UI. Phone Link cannot relay that call to a Bluetooth headset (Microsoft says so).
Users also report that it grabs the headset's hands-free channel.

**The public API is call control around an OS-owned audio path.**
`PhoneLineTransportDevice` arrived in Windows 10 1903 (`CallsPhoneContract` 5).
Microsoft describes it as representing the hardware device of a `PhoneLine`,
"currently only supported for use with bluetooth devices". The app calls
`RequestAccessAsync`, `RegisterApp` and `Connect`; Windows then sets up the HFP
service-level connection. `AudioRoutingStatus` reports where the audio goes.

- **Capability and identity.** These APIs need the `phoneLineTransportManagement`
  capability, which is on Microsoft's **restricted** capability list. A capability
  can only be declared by an app with package identity (MSIX, or a sparse package
  for an otherwise unpackaged Win32 app). Saiph currently ships as an unpackaged
  desktop app, so it cannot use these APIs as it stands. This ties B2 on Windows
  to the same packaging decision as the share sheet (plan item H).
- **Broken or gated since 22H2.** The MyPhone maintainer
  ([issue #26](https://github.com/BestOwl/MyPhone/issues/26), opened 12 March 2023)
  documents the following:
  - `RequestAccessAsync` returns `DeniedBySystem` on Windows 11 22H2, and
    `ConnectAsync` fails on Windows 10 22H2. It still worked on Windows 10 21H2
    and LTSC 2021.
  - Phone Link calls `TryUnlockPhoneLineTransportDeviceAPIs` and contains a
    `ShouldSkipLAFCheck()` path. This points to a Limited Access Feature gate
    that Microsoft has not documented.
  - A 2024 comment reports that a registry bypass made registration succeed, but
    calls still did not work.
  - An April 2026 comment reports that another app's registration (for example
    Phone Link) blocks a second app for the same phone until the phone is
    unpaired.
  - Some commenters said CallCenter, Intel Unison and Thy Phone still worked on
    22H2. That is unverified.
- **Audio.** MyPhone ran its own HFP over RFCOMM. It got the service-level
  connection and could dial, but "failed to establish SCO audio connection"
  ([README](https://github.com/BestOwl/MyPhone)). Another user hit the same wall
  ([issue #27](https://github.com/BestOwl/MyPhone/issues/27)). The README
  concludes that only a custom user-mode profile driver could carry audio, and
  that MSIX cannot install drivers. In contrast, In The Hand's **Thy Phone** (a
  Store app) offered calls "with your PC microphone and speakers" from Windows 10
  2004. In 2022 it rebuilt its call UI after 22H2 deprecated the system call
  dialog, and it kept a "switch audio to the phone" control. This suggests the
  OS-owned path does carry audio *for an app Windows accepts as the registered
  one*. We found no public documentation of how a new app obtains that
  acceptance today.
- **Others.** Dell Mobile Connect was discontinued in January 2023. Intel Unison
  wound down in June 2025 and was removed from the Store in July 2025. Both were
  OEM-bundled apps with Microsoft relationships. Neither published how it got
  call audio. No open-source Windows project is known to carry two-way call audio
  today.

**Unpackaged/non-Store apps:** not possible, because the capability needs package
identity. **Packaged but sideloaded:** restricted capabilities can be sideloaded
without Store approval. The undocumented gate and the conflict with Phone Link
remain.

**Windows verdict: no-go for committing to the feature now.** Evidence is weak in
both directions. Thy Phone suggests it can work. MyPhone and later reports
suggest it is now reserved to Phone Link. One time-boxed check on the owner's
25H2 PC settles it (section 7). Until then, Windows users who want to talk
through the PC can keep Phone Link's Calls feature on alongside Saiph. That is an
honest, explicit parity gap.

## 4. Linux findings

**Roles and components.** PipeWire's native BlueZ backend implements HSP/HFP
itself; oFono is no longer needed. WirePlumber chooses the roles. The `hfp_hf`
role makes the computer a hands-free unit for a phone.

- WirePlumber **0.5** (`bluez5.roles`) defaults to
  `[ a2dp_sink a2dp_source bap_sink bap_source hfp_hf hfp_ag ]`, with backend
  `native`
  ([docs](https://pipewire.pages.freedesktop.org/wireplumber/daemon/configuration/bluetooth.html)).
- WirePlumber **0.4** (`bluez5.headset-roles`) defaults to `[ hsp_hs hfp_ag ]`.
  `hfp_hf` must be added
  ([0.4 docs](https://jij.pages.freedesktop.org/wireplumber/configuration/bluetooth.html)).
  The 0.4 Lua files are read from `~/.config/wireplumber/bluetooth.lua.d/` too,
  so no root is needed.
- In the HF role, PipeWire creates the call stream nodes
  (`bluez_input.<MAC>.headset-audio-gateway` and the matching output) as streams.
  WirePlumber links them to the default devices. A PipeWire issue notes that they
  do not carry the "Communication" media role, so routing may need a nudge.

**Call control without root (new).** PipeWire **1.4.0** (6 March 2025) added a
"Telephony D-Bus API compatible with ofono". The `spa/plugins/bluez5/telephony.c`
source shows how it works:

- It runs on the **session bus** by default as `org.pipewire.Telephony`.
- Objects live at `/org/pipewire/Telephony/agN` and `/agN/callM`.
- `AudioGateway1` offers `Dial`, `HangupAll`, `SwapCalls`, `HoldAndAnswer`,
  `SendTones` and others. `Call1` offers `Answer` and `Hangup`, with
  `LineIdentification`, `Name` and `State`.
  `AudioGatewayTransport1` offers `Activate`, `Codec` and a writable `RejectSCO`.
- There is an optional oFono-compatible mode on the system bus.
- It is controlled by `bluez5.telephony-dbus-service`.

So on PipeWire ≥ 1.4, Saiph can answer, hang up, dial and pull the audio to the
computer as the logged-in user, without oFono or root. PipeWire 1.5.81–1.5.84
added further telephony fixes.

**BlueZ.** The BlueZ ChangeLog adds HFP work in 5.84–5.86 and an experimental
`org.bluez.Telephony1` interface (5.86). Its properties describe the remote
gateway (signal, battery, operator), so it is a BlueZ-side HF client API. We did
not confirm whether distribution builds enable it, or whether it competes with
PipeWire's native backend for the hands-free profile. The prototype should check
(see risks).

**What a desktop user needs.**

| Ubuntu | Packages | User action |
| --- | --- | --- |
| 26.04 LTS | Default install (PipeWire 1.6.2, WirePlumber 0.5.13, BlueZ 5.85) | Pair the phone. Allow "Phone calls" for the computer on the phone |
| 24.04 LTS | Default install (PipeWire 1.0.5, WirePlumber 0.4.17, BlueZ 5.72) | As above, plus one per-user WirePlumber file. Saiph writes it only after the user agrees (section 6) |
| 22.04 LTS | PulseAudio by default; PipeWire 0.3.48 and WirePlumber 0.4.8 only in universe | Replace the sound server or install oFono. Root and system-wide changes, so Saiph will not do it |

Versions come from Launchpad on 14 October 2026.

**Detection without changing anything.** `src/orion_mini/call_audio_probe.py`
(added in this spike, not wired into the app) reads the following:

- `pipewire --version`, `wireplumber --version` and `bluetoothctl --version`;
- `pactl info` (is the server PipeWire?);
- `bluetoothctl show`: does the adapter advertise the **Handsfree UUID
  `0000111e-…`**? That is the live proof that something registered the HF role;
- `busctl --user list` (is `org.pipewire.Telephony` present?) and
  `busctl --system list` (is oFono running, which may claim the role?);
- WirePlumber configuration files in packaged, `/etc` and user order.

It returns `audio: ready | needs-setup | unsupported | unknown` and
`call_control: hfp | app`, with plain-language issues. It never writes
configuration, restarts a service or opens a connection. Unit tests use
synthetic fixtures (`tests/test_call_audio_probe.py`).

**Interaction with Saiph's existing call alerts.** Keep Saiph's phone-app events
as the source of truth for the call UI. They carry contact names, work without
Bluetooth, and already drive the alerts, answer/decline and pause-media-on-calls.
HFP adds only the audio route:

- **Answer here:** send the existing `call.command answer`. If
  `call_control == hfp`, also make sure the transport is active
  (`AudioGatewayTransport1.Activate`, `RejectSCO=false`), so the audio comes to
  the computer.
- **Answer on phone:** send the existing `call.command answer`, but leave
  `RejectSCO=true` (or let the phone keep the audio).
- **Move audio to this computer:** `Activate`. Moving it back is done from the
  phone's call screen. We found no HF-side "release audio" method in the
  PipeWire API.
- **When the phone app is offline** but Bluetooth is connected, fall back to
  `Call1.Answer`/`Hangup` and `LineIdentification`.
- **Matching:** the user picks the paired Bluetooth phone, as the Linux automatic
  lock already does. Calls are correlated by number and timing.
- **No double ringing:** the phone may send its ringtone in-band over SCO
  (`InbandRingtone`). Saiph should rely on its own alert and not open the audio
  until the call is answered here.

## 5. Android side

- **Nothing new is required for the basic case.** The user pairs the computer in
  the phone's Bluetooth settings. On the computer's device page they keep "Phone
  calls" on, and they may turn "Media audio" off. Android routes call audio to
  the active HFP device automatically. Saiph's existing `acceptRingingCall()`
  answer path then plays through the computer.
- **Optional helpers (GPL-3.0 app, platform APIs only):**
  - Report whether the paired computer is connected as a hands-free device. Use
    the `BluetoothProfile.HEADSET` proxy's `getConnectedDevices()`, which needs
    `BLUETOOTH_CONNECT` (already declared). Report it as a new event type, so the
    desktop can show "Talk on <computer>".
  - Open `Settings.ACTION_BLUETOOTH_SETTINGS` with guidance for pairing.
- **Limits:**
  - A non-dialer app cannot move a cellular call's audio. The `InCallService`
    audio-route APIs are for the default dialer, and `BluetoothHeadset`
    `connectAudio`/`setActiveDevice` are system-only.
  - Android has one *active* HFP device at a time, so earbuds and the computer
    compete for it.
  - In range, the phone may send every call to the computer until the user picks
    another output.
- **Dual SIM:** HFP has no SIM selection. `ATD`/`Dial` and Saiph's `placeCall`
  both use the phone's default SIM, or the phone's own prompt (see B1 acceptance).
- **VoIP apps (WhatsApp, Signal, Teams…):** the brief's assumption that they
  "do not use HFP" is only partly right. Apps that support Bluetooth headsets send
  their audio over SCO, so audio may reach the computer. Call control over HFP
  works only for apps integrated with Android Telecom (self-managed
  `ConnectionService`). Android documents those calls as visible and controllable
  from Bluetooth devices. Other apps' calls do not appear in `+CLCC`. Behaviour is
  per app, so test it and do not promise it.

## 6. Recommended architecture (Linux first)

1. **Probe** (done): `call_audio_probe.probe()` decides whether the setting is
   shown and what it says.
2. **Setting** ("Use this computer for call audio", off by default, Linux only):
   - The user chooses the paired phone.
   - On WirePlumber 0.4, with consent, Saiph writes the reversible per-user file
     `~/.config/wireplumber/bluetooth.lua.d/51-saiph-hfp-hf.lua`, containing:
     `bluez_monitor.properties["bluez5.headset-roles"] = "[ hsp_hs hfp_hf hfp_ag ]"`.
     It then restarts `wireplumber` *as the user* and warns that this briefly
     interrupts audio.
   - Turning the setting off removes the file.
   - Nothing under `/etc`, and no package installs.
3. **Call audio adapter:**
   - Talks to `org.pipewire.Telephony` on the session bus, through the pure-Python
     MIT library `jeepney` (already pulled in on Linux by `SecretStorage` in the
     hosted extra) or through `busctl --user` subprocess calls.
   - Exposes `answer_here`, `move_audio_here` and `state` to the existing Calls
     UI. Where PipeWire has no telephony API (before 1.4, e.g. Ubuntu 24.04),
     it falls back to Saiph's app commands.
4. **Hub/Link:** no changes for Linux audio. All Bluetooth traffic is local, and
   nothing about audio goes to the Hub.
5. **Windows:** only after a successful gate test (section 7), and together with
   the MSIX/sparse-package decision.
   - A small packaged C#/WinRT helper with `phoneLineTransportManagement`
     registers the phone and reports `AudioRoutingStatus`.
   - The Python app drives it through the existing local interface.
   - Phone Link's Calls must be off for that phone.

## 7. Time-boxed prototype plan (5 working days)

These are owner-run physical tests. Use your own two phones (one paired, one to
call it), test numbers only, and do not record call content. Write down every
result, including failures. These tests are the only acceptance evidence; the
unit tests prove nothing about audio.

### Day 0: preparation (½ day, Linux and Windows)

- Charge both phones. Note the paired phone's model, Android version and dialer.
- Have the probe ready: run `PYTHONPATH=src python3 -c "import json; from orion_mini.call_audio_probe import probe; print(json.dumps(probe(), indent=2))"`
  from the repository on the Linux PC.

### Linux (target Ubuntu 26.04; repeat steps L1–L6 on 24.04 if available): 2½ days

| Step | Do | Expect / record |
| --- | --- | --- |
| L0 | `lsb_release -d; pipewire --version; wireplumber --version; bluetoothctl --version; pactl info \| grep 'Server Name'`, then the probe | Versions, `audio`, `call_control`, issues |
| L1 | 24.04 only: create the user file from section 6, then `systemctl --user restart wireplumber`. Run `bluetoothctl show \| grep -i handsfree` | A line with `Handsfree (0000111e-…)`. The probe now says `ready`. 26.04 should show it with no file |
| L2 | Pair from the phone: Settings → Bluetooth → Pair new device → the computer. On its details page keep "Phone calls" on. Then `bluetoothctl info <phone MAC>` | `Connected: yes`, UUID `Handsfree Audio Gateway (0000111f-…)` |
| L3 | `wpctl status` | A Bluetooth device for the phone with a headset/audio-gateway profile |
| L4 | Call the paired phone from the second phone. Answer **on the paired phone**. Run `pw-link -l` and `wpctl status` during the call | Caller heard on the PC speakers, PC microphone heard by the caller. Record the latency feel, echo and whether nodes were linked automatically. If audio does not arrive: note the node names, try `pw-link` manually and record whether that fixes it |
| L5 | 26.04 only: `busctl --user tree org.pipewire.Telephony`. Place a call to the paired phone; `busctl --user call org.pipewire.Telephony <call path> org.pipewire.Telephony.Call1 Answer`, then `… Hangup`. Dial: `busctl --user call org.pipewire.Telephony <ag path> org.pipewire.Telephony.AudioGateway1 Dial s <second phone number>` | Answer, hang-up and dial work. Record the object paths, `LineIdentification`, `Codec` (CVSD or mSBC) and the `RejectSCO` default |
| L6 | Answer a call via Saiph's existing desktop "Answer" button (Saiph running as normal) | Audio comes to the PC without touching the phone. Record whether Saiph's media pause still behaves |
| L7 | Edge cases: walk the phone out of range mid-call; switch output on the phone's call screen; a WhatsApp or Signal call; dual-SIM dial if available | Audio falls back to the phone; the switch works both ways; note VoIP behaviour per app |
| L8 | Roll back: delete the user file, `systemctl --user restart wireplumber`, and optionally unpair | Probe returns to its L0 state |

**Linux go criteria:** two-way audio in L4 on 26.04 with no root changes, and L5
or L6 answering works. **No-go:** audio needs root changes, or WirePlumber
crashes on `hfp_hf`. One Gentoo report saw a crash; record any crash.

### Windows (owner's Windows 11 25H2 PC): at most 2 days, stop at the first hard failure

| Step | Do | Expect / record |
| --- | --- | --- |
| W0 | `winver`; Device Manager → Bluetooth adapter make and driver version; phone → Properties → Services | Build number; whether "Handsfree Telephony" is listed |
| W1 | Baseline with Phone Link (already part of Windows): turn on Calls, make and receive a test call | Two-way audio through the PC. This proves the adapter and driver support HF. If this fails, stop: no app can do better on this PC |
| W2 | **Only with the owner's agreement, on a test PC:** build a minimal packaged C#/WinRT harness. It declares `phoneLineTransportManagement`, is dev-signed and sideloaded, and is based on MyPhone's diagnostic approach. First turn off Phone Link's Calls for the phone | Result of `RequestAccessAsync` (`Allowed`/`DeniedBySystem`), `RegisterApp`, `ConnectAsync` |
| W3 | With W2 registered: receive a test call and answer it on the phone; then dial via `PhoneLine.Dial` | `AudioRoutingStatus`, and whether audio is heard on the PC both ways |
| W4 | Clean up: `Get-AppxPackage *harness* \| Remove-AppxPackage`, turn Phone Link Calls back on, and re-pair if needed | Phone Link calls work again |

Do not use registry bypasses or Limited Access Feature tokens that were not
issued to Saiph.

**Windows go criteria:** W3 gives two-way audio on 25H2 without bypasses, and
Phone Link can be turned off cleanly. Then decide on MSIX or sparse packaging.
**No-go:** `DeniedBySystem`, or registration without audio. Then record Windows as
"use Phone Link for call audio" in the parity table, and ask Microsoft about
access to the Limited Access Feature.

### Decision (½ day)

Fill in the results, update the B2 row and decide about the website wording.
Keep "Answer from your desk" (true today). Do not advertise talking through the
computer until the relevant platform passes.

## 8. Licensing

| Component | Licence | Use | Compatible? |
| --- | --- | --- | --- |
| BlueZ | GPL-2.0-or-later (daemon) | Separate system service over D-Bus and its CLI; not linked | Yes (no linking) |
| PipeWire, WirePlumber | MIT | Session services over D-Bus and CLI | Yes |
| oFono | GPL-2.0-only | Not used; it would only be a separate process over D-Bus | Yes if ever needed (no linking) |
| jeepney (D-Bus for Python) | MIT | Optional for the adapter | Yes with AGPL-3.0 |
| Windows `Windows.ApplicationModel.Calls` | OS API | Packaged helper | Yes. Platform APIs are system libraries |
| MyPhone (reference only) | MIT | Read for approach; any copied code keeps its notice | Yes |
| Google Bumble | Apache-2.0 | Not recommended | Compatible with (A)GPL-3.0, but alpha |
| BTstack | Non-commercial / commercial licence | Not used | **No** |
| Android platform APIs | — | GPL-3.0 app | Yes |

## 9. Risks

- **Windows gate (high):** an undocumented Limited Access Feature, one registered
  app per phone, and restricted-capability packaging. Microsoft can change any of
  them without notice.
- **Linux role conflicts (medium):**
  - oFono, or BlueZ's own newer HFP/Telephony code, may claim the hands-free
    profile.
  - When two Linux machines both run PipeWire, they each act as HF *and* AG to
    the other (a PipeWire fix exists).
  - The probe reports oFono, but cannot tell who registered the role.
- **Routing (medium):** call stream nodes lack the "Communication" role, so
  automatic linking may pick the wrong device. Saiph may need to link them
  explicitly with `pw-link` or a loopback.
- **User surprise (medium):** while the computer is connected as a hands-free
  unit, the phone may send *every* call's audio to it. Saiph must make the state
  visible, keep the setting off by default and explain how to switch back on the
  phone.
- **Headset contention (low/medium):** earbuds and the computer compete for the
  single active HFP device.
- **Audio quality (low/medium):** narrowband CVSD on adapters without mSBC; echo
  without cancellation. PipeWire has an echo-cancel module, which should be
  evaluated in the prototype.
- **Evidence quality:** every audio claim above comes from documentation, source
  code or community reports, not from our own hardware tests.

## Sources (accessed 14 October 2026)

- Microsoft: [PhoneLineTransportDevice](https://learn.microsoft.com/en-us/uwp/api/windows.applicationmodel.calls.phonelinetransportdevice?view=winrt-26100); [App capability declarations (`phoneLineTransportManagement`, restricted)](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/app-capability-declarations); [LimitedAccessFeatures](https://learn.microsoft.com/en-us/uwp/api/windows.applicationmodel.limitedaccessfeatures?view=winrt-26100); [Bluetooth HFP bypass audio streaming](https://learn.microsoft.com/windows-hardware/drivers/audio/bluetooth-hfp-bypass-audio-streaming); [Setting up calls in Phone Link](https://support.microsoft.com/help/4531605); [Troubleshooting calls in Phone Link](https://support.microsoft.com/en-gb/topic/troubleshooting-calls-in-the-phone-link-app-1644add0-a51e-ff32-1b55-82b1ecf6b359)
- MyPhone: [README](https://github.com/BestOwl/MyPhone); [issue #26: API broken on 22H2](https://github.com/BestOwl/MyPhone/issues/26); [issue #27: no call audio](https://github.com/BestOwl/MyPhone/issues/27)
- In The Hand: [Thy Phone (2021)](https://inthehand.com/2021/02/16/new-windows-phone-app/); [Thy Phone for Windows 11 (Oct 2022)](https://inthehand.com/2022/10/26/thy-phone-for-windows-11/)
- [Dell Mobile Connect end of service](https://www.dell.com/support/kbdoc/en-us/000199082); [Intel Unison discontinued (Tom's Hardware)](https://tomshardware.com/software/intel-discontinues-unison-app-for-connecting-pcs-and-smartphones)
- [KDE bug 345686 (answer calls; Bluetooth audio discussion)](https://bugs.kde.org/show_bug.cgi?id=345686)
- WirePlumber: [Bluetooth configuration (0.5)](https://pipewire.pages.freedesktop.org/wireplumber/daemon/configuration/bluetooth.html); [Bluetooth configuration (0.4)](https://jij.pages.freedesktop.org/wireplumber/configuration/bluetooth.html)
- PipeWire: [NEWS (1.4.0 Telephony D-Bus API)](https://github.com/PipeWire/pipewire/blob/master/NEWS); [`spa/plugins/bluez5/telephony.c`](https://github.com/PipeWire/pipewire/blob/master/spa/plugins/bluez5/telephony.c); [issue 2531 (HFP stream media role)](https://gitlab.freedesktop.org/pipewire/pipewire/-/issues/2531); [MR 1707 (simultaneous HF & AG)](https://gitlab.freedesktop.org/pipewire/pipewire/-/merge_requests/1707); [Gentoo forum: crash with `hfp_hf`](https://forums.gentoo.org/viewtopic.php?p=8867103)
- BlueZ: [ChangeLog](https://github.com/bluez/bluez/blob/master/ChangeLog); [org.bluez.Telephony(5)](https://man.archlinux.org/man/org.bluez.Telephony.5.en)
- PulseAudio: [Bluetooth documentation (oFono for HFP)](https://wiki.freedesktop.org/www/Software/PulseAudio/Documentation/User/Bluetooth/)
- Ubuntu package versions: Launchpad [pipewire](https://launchpad.net/ubuntu/+source/pipewire), [wireplumber](https://launchpad.net/ubuntu/+source/wireplumber), [bluez](https://launchpad.net/ubuntu/+source/bluez)
- Android: [ConnectionService (self-managed calls and Bluetooth)](https://developer.android.com/reference/android/telecom/ConnectionService); scrcpy [audio sources](https://github.com/Genymobile/scrcpy/blob/master/doc/audio.md)
- [Google Bumble](https://android.googlesource.com/platform/external/python/bumble/+/HEAD/examples/run_hfp_handsfree.py)
