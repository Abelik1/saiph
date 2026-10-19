# Calls through this computer (B2)

Research: [research/CALL_AUDIO_SPIKE.md](research/CALL_AUDIO_SPIKE.md). Plan item B2 in
[PHONE_LINK_PARITY.md](PHONE_LINK_PARITY.md).

**Owner rule:** call audio uses Bluetooth Hands-Free (HFP) only, directly between the
phone and this computer. It is never relayed through Saiph Cloud, a Hub or the droplet.
No new Cloud or Hub message exists; `call.command` is unchanged.

**Priority (owner, 18 October 2026):** Windows + Android first; Linux is step two.

| Platform | State | Next step |
| --- | --- | --- |
| Windows 11 | Gate test harness ready to run in one step; **not yet run** | Owner runs `run-gate.ps1` on a PC with Bluetooth (below) |
| Linux (PipeWire) | Prototype built in the app, unit-tested only | Owner's physical tests on the Ubuntu laptop (Linux section) |
| Android | No app change needed: the phone is the Bluetooth audio gateway | Keep "Phone calls" on for the computer in the phone's Bluetooth settings |

## Windows: one-step gate test

### Findings so far (18 October 2026, the owner's desktop)

- Windows 11 25H2, build 26200.9711. Phone Link 1.26082.121.0 is installed.
- **The PC has no Bluetooth radio** (MSI MS-7C37 board, no Bluetooth devices, Bluetooth
  service stopped). The A55 is attached over USB only. The harness's read-only probe
  found zero radios and zero hands-free devices.
- So **no part of the gate can run on this PC**: `RequestAccessAsync` is a method of a
  `PhoneLineTransportDevice`, and those exist only for a phone paired over Bluetooth
  with Phone calls on (device selector: Handsfree Audio Gateway UUID `0000111f`).
- The sparse-package manifest (restricted `phoneLineTransportManagement`, `phoneCall`,
  `runFullTrust`) passes `makeappx` schema validation. Nothing was installed or
  trusted on this PC.
- `TryUnlockPhoneLineTransportDeviceAPIs` (seen in Phone Link, per MyPhone issue #26)
  has no public documentation or Limited Access Feature ID; the harness records the
  exact refusal instead.

### The harness

`native/windows-call-audio-gate/`: a self-contained C# program (`Program.cs`), a sparse
package manifest (`package/AppxManifest.xml`) and an embedded `msix` identity element
(`app.manifest`), so the exe runs with package identity from its external folder.

- Developer PC: `powershell -NoProfile -ExecutionPolicy Bypass -File native\windows-call-audio-gate\gate.ps1`
  builds `out\SaiphCallAudioGate.zip` (self-contained exe, signed `gate.msix`, `gate.cer`,
  `run-gate.ps1`, `README.txt`). The test certificate is made in memory, written to files
  only, valid for 30 days, and its private key is deleted after signing. It needs the
  .NET 9 SDK and the Windows SDK; the owner's test PC needs neither.
- Harness steps: `probe` (read-only), `access` (`RequestAccessAsync`), `register`
  (`RegisterApp`), `connect` (`ConnectAsync`), `watch N` (call state and
  `AudioRoutingStatus` changes), `unregister`. Each prints one JSON report.

### Owner steps (Windows 11 PC with Bluetooth, about 15 minutes)

Full instructions and what each result means are in the bundle's `README.txt`.

1. Pair the A55 with that PC over Bluetooth; on the phone keep **Phone calls** on for it.
2. Unzip `SaiphCallAudioGate.zip`, open PowerShell in the folder and run
   `powershell -NoProfile -ExecutionPolicy Bypass -File .\run-gate.ps1` (add `-Device "A55"`
   if several phones are paired).
3. Answer the prompts. It asks before every change: one administrator prompt trusts the
   test certificate (`LocalMachine\TrustedPeople`) and it registers the hidden test
   package; step 4 (optional) registers it as the phone's hands-free app, connects, and
   watches one real call answered on the phone while you listen on the PC.
4. At the end it unregisters, removes the package and removes the certificate (second
   administrator prompt). Send back `results\gate-<time>.json` and `.md`.

| Verdict | Meaning | Next |
| --- | --- | --- |
| not testable (no Bluetooth / phone not paired for calls) | Missing hardware or pairing | Fix and run again |
| no-go (DeniedBySystem) | Windows keeps the API for Phone Link | Ask Microsoft (below); Windows users keep Phone Link Calls |
| DeniedByUser | Privacy setting blocks apps | Allow in Settings > Privacy & security > Phone calls, run again |
| registration works but no two-way audio | Windows does not give the audio to this app | No-go; same as DeniedBySystem |
| GO: two-way call audio through the PC | It works | Build the Windows path with package identity for Saiph |

### If Windows says no

What Microsoft would have to grant, in order of likelihood:

1. A **Limited Access Feature** unlock for the phone-line transport APIs (token and
   attestation issued to Saiph's package family name). There is no public request form;
   it goes through Microsoft partner contacts. Cost: no fee is published; time and a
   commercial relationship.
2. **Package identity** for Saiph in any case: a sparse package (signed MSIX next to the
   existing installer) or a full MSIX. A trusted code-signing certificate is needed
   (the release signing identity, or Azure Trusted Signing at about USD 10 a month).
3. Store submission is not required for restricted capabilities when sideloaded, but a
   Store listing would need Microsoft's approval of `phoneLineTransportManagement`.

The other routes stay no-go: a custom HFP profile driver plus audio driver (kernel driver
signing, EV certificate, admin install), or a user-space Bluetooth stack on a dedicated
dongle (takes the adapter away from Windows). Until then the honest answer for Windows
users is Phone Link's Calls alongside Saiph, which the Calls tab already says.

## Linux (step two): the prototype in the app

### What is built (unit-tested only)

- `src/orion_mini/call_audio.py` (Linux only; inert on Windows and macOS):
  - Detection, read-only and cached for 20 s on a worker thread: PipeWire, WirePlumber and
    BlueZ versions (through `call_audio_probe.py`), the adapter (`bluetoothctl show`: present,
    powered, Handsfree UUID registered), paired phones (`bluetoothctl info`: paired, connected,
    offers Handsfree Audio Gateway `0000111f`), and PipeWire's `org.pipewire.Telephony`
    gateways (PipeWire 1.4 and later, `busctl --user`).
  - Readiness: `checking | unsupported | no-adapter | bluetooth-off | needs-setup |
    choose-phone | not-paired | no-calls-profile | phone-away | ready`.
  - Setup, only when the user clicks it: writes Saiph's own per-user WirePlumber file
    (`~/.config/wireplumber/bluetooth.lua.d/51-saiph-hfp-hf.lua` on 0.4,
    `wireplumber.conf.d/51-saiph-hfp-hf.conf` on 0.5), keeping the user's roles and adding
    `hfp_hf`, then `systemctl --user restart wireplumber`. It never overwrites a file it did
    not write. "Remove Saiph's hands-free file" undoes it. No root, nothing under `/etc`.
  - Per call: on `ringing` it sets `RejectSCO=true` (audio stays on the phone, no second
    ringtone here) and remembers the old value. "Answer here" sends the unchanged
    `call.command answer`, then sets `RejectSCO=false`, calls `Activate` once the call is live
    and reports `here` (with codec) or `on-phone` with an honest message after 10 s. "Answer on
    phone" keeps the audio held on the phone. "Move audio here" works during a live call.
    `ended`/`missed` restores `RejectSCO`. A stuck session is cleared when no call is live.
    Without the telephony interface (PipeWire < 1.4), the route is confirmed by the phone's
    `bluez_*` nodes in `pactl list short`.
  - Fallback: if the phone app cannot be reached, Answer/Decline use `Call1.Answer`/`Hangup`
    over Bluetooth when a ringing call is visible there.
- Wiring: setting `link.call_audio {enabled, device}`; state key `call_audio`; bridge methods
  `call_audio.refresh|setup|remove_setup|move_here`; `phone.call` accepts an optional local
  `audio: "here" | "phone"` that is never sent to the phone; Link and Cloud call-state events
  both feed `call_state`.
- UI: Phone → Calls has a "Talk through this computer" card (status badge, three setup steps,
  phone picker, on/off switch, consented setup, Check again, details). The ringing call shows
  "Answer here" / "Answer on phone" / "Decline"; the banner says "Answer here" when ready.
  Windows shows one honest line: call audio stays on the phone; Phone Link's Calls can be used.
- Tests: `tests/test_call_audio.py` (fake computer and telephony bus) and
  `frontend/src/workspace/CallAudio.test.tsx`.

### Linux physical tests (nothing here is proven on hardware)

Owner's Samsung A55, the Ubuntu laptop, and a second phone to call from. Test numbers only;
do not record call content. Run Saiph from this branch in an isolated profile.

1. **Baseline:** `lsb_release -d; pipewire --version; wireplumber --version; bluetoothctl --version`.
   Open Phone → Calls and record the card's badge, message and Details.
2. **Pair:** on the phone, Settings → Connections → Bluetooth → pair the laptop; on its
   details page keep **Phone calls** on. Click **Check again**. Expect step 3 not yet done until
   you choose the phone.
3. **Setup (24.04 / WirePlumber 0.4 only):** click **Turn on hands-free**. Expect the file
   named in the card and `bluetoothctl show | grep -i handsfree` to list `0000111e`. On 26.04
   expect no setup step.
4. **Turn on:** choose the phone in the picker, switch on. Expect badge **On**.
5. **Answer here:** call the A55 from the second phone. Expect no ringtone through the laptop
   speakers (only Saiph's alert). Click **Answer here**. Expect "Talking through this computer ·
   CVSD/mSBC", caller heard on the laptop, laptop mic heard by the caller. Record delay, echo,
   and `busctl --user tree org.pipewire.Telephony`, `wpctl status`, `pw-link -l`.
6. **Answer on phone:** repeat, click **Answer on phone**; expect audio on the A55. Then click
   **Move audio here**; expect it to move.
7. **Answer on the handset itself** (not in Saiph): expect the audio to stay on the phone.
8. **End:** hang up from either side; expect the session to clear. Run
   `busctl --user get-property org.pipewire.Telephony /org/pipewire/Telephony/ag1 org.pipewire.Telephony.AudioGatewayTransport1 RejectSCO`
   and record that it matches the value before the call.
9. **App offline fallback:** force-stop Saiph on the phone, call it, click **Answer here**
   (then repeat with **Decline**). Expect it to work over Bluetooth on PipeWire 1.4 and later.
10. **Edge cases:** walk out of range mid-call; earbuds connected at the same time; a WhatsApp
    or Signal call; Saiph Cloud and self-hosted Hub modes both (audio must never touch the network).
11. **Roll back:** **Remove Saiph's hands-free file**, switch off, optionally unpair.

Record failures, especially: audio not linked to the speakers automatically (the spike notes
missing "Communication" roles), WirePlumber crashes with `hfp_hf`, or oFono claiming the role.
