# Connecting without a QR code

Status: implemented on branch `claude/qrless-pairing-1ab996`; unit tested on all
sides; **not yet accepted on a physical phone and computer** (see the checklist
at the end). The QR code remains available in both flows as a fallback.

Two separate problems used a QR code:

1. **Linking a phone to the Saiph account's main computer** (once per phone).
2. **Starting a camera session** on an already linked phone (every time).

They need different solutions because they have different trust starting points:
before linking, the phone has no authenticated channel to the computer; after
linking, both share the end-to-end encrypted Saiph Cloud mailbox.

## Today's flows (before this change)

### Device linking (Saiph Cloud)

| Step | Where | What it carries | Security property |
| --- | --- | --- | --- |
| Main computer shows a root QR | `HostedController.root_code` [hosted_runtime.py](../src/orion_mini/hosted_runtime.py) → `make_root_code` [hosted_approval.py:153](../src/orion_mini/hosted_approval.py) | `orion-root-v1:` signed JSON: deployment ID, root device ID, root **public** signing and encryption keys, 5-minute expiry, random nonce | Public data only. Authenticity comes from the visual channel: the owner points their own phone at their own screen. |
| Phone scans and checks it | `OrionQrActivity` [OrionQrActivity.kt:32](../android/app/src/main/java/com/orionmini/mobile/OrionQrActivity.kt), `HostedApprovalCodes.inspect` [HostedApprovalCodes.kt:14](../android/core/network/src/main/java/sefirah/network/orion/HostedApprovalCodes.kt), `HostedActivity.checkRoot`/`confirmRootScreen` [HostedActivity.kt](../android/app/src/main/java/com/orionmini/mobile/HostedActivity.kt) | — | Self-signature + expiry; the owner confirms the 64-hex root fingerprint, then screen-lock verification. |
| Phone pins root, creates keys, requests approval | `HostedRuntime.enroll` [HostedRuntime.kt:262](../android/app/src/main/java/com/orionmini/mobile/HostedRuntime.kt), `HostedApprovalCodes.request` | `orion-approve-v1:` request signed by the new device key, bound to the root fingerprint; submitted to `/v1/devices/requests` and offered via `/v1/devices/approval-requests` | Proof of key possession; binding to the pinned root. The relay is untrusted. |
| Main computer approves | `offered_requests`/`approve` [hosted_runtime.py](../src/orion_mini/hosted_runtime.py), `verify_request_code` [hosted_approval.py:225](../src/orion_mini/hosted_approval.py) | — | The owner compares the full device fingerprint (`device_fingerprint`) on both screens; **native owner verification** (Windows Hello) before the root signs the new roster. |

The QR's single job is an authentic **computer → phone** transfer of the root's
public keys. The reverse direction is authenticated by the owner comparing the
device fingerprint on the computer.

### Camera sessions

| Step | Where | What it carries | Security property |
| --- | --- | --- | --- |
| Computer starts a session | `CameraSession.start` [camera_session.py:133](../src/orion_mini/camera_session.py) | `orion-camera:1:`/`:2:` base64 JSON: 128-bit session ID, RFC 1918 IPv4 addresses, port, SHA-256 pin of an ephemeral P-256 TLS certificate, **256-bit one-use bearer secret**, 2-minute deadline, optional stream profile | The secret is a private capability; the pin defeats a LAN man in the middle; the desktop claims the secret before WebSocket upgrade and accepts one connection (`_authorize`, line 184). |
| Phone scans | `CameraOffer.parse` [CameraOffer.kt:23](../android/app/src/main/java/com/orionmini/mobile/CameraOffer.kt) | — | Strict shape, private literal IPv4 only, expiry ≤ 120 s. |
| Phone starts capture | `PhoneCameraActivity` | — | Screen-lock owner verification, Android camera permission, foreground only. |

### LAN discovery already present

The inherited Sefirah transport (`android/core/network/.../NetworkDiscovery.kt`,
`NsdService.kt`) broadcasts and resolves devices for the legacy direct desktop
protocol. Hosted (Saiph Cloud) linking and the integrated camera do not use it.
The new flow does not reuse it either: it carries no Hosted keys and has its own
pairing semantics.

## (b) Camera sessions: delivered through Saiph Cloud

**Implemented.** The desktop keeps showing the QR, and additionally sends the
exact same invitation to the linked phone inside a sealed envelope:

```json
{"type": "session.offer", "version": 1, "id": "<128-bit hex>",
 "service": "camera", "expires_at": 1800000090, "invite": "orion-camera:2:..."}
```

- Shared format: [session_offer.py](../src/orion_mini/session_offer.py) and
  [SessionOffer.kt](../android/app/src/main/java/com/orionmini/mobile/SessionOffer.kt),
  checked against the same vectors in
  `android/app/src/test/resources/session-offer-vectors.json` by both test suites.
- Exact keys and types; `service` is an allow list whose entry parses its own
  invitation (camera: the scanner's own checks); `expires_at` must equal the
  invitation deadline, be in the future and at most 120 s ahead.
- Sender: `HostedController.session_offer` seals it to one current roster member
  that is a known, online phone; envelope TTL ≤ the invitation's remaining time.
  The web UI passes only the session ID and phone ID (`camera.offer` bridge
  method); the invitation never crosses into web content.
- Receiver: `HostedRuntime` accepts it only from a current **subscribed computer**,
  claims a durable receipt `offer:<id>` (replay), keeps it in memory only
  (`SessionOffers`, shown once, taken once, dropped on expiry, revocation or
  sign-out) and posts a local-only notification **Start camera for <computer>?**
  whose intent carries only the offer ID. Tapping opens `PhoneCameraActivity`,
  which still requires screen-lock verification, Android camera permission and
  the foreground. Nothing starts without the tap.
- One-use: the desktop erases the bearer secret on first claim, so a replayed
  offer, a second phone or a later QR scan gets nothing.
- Compatibility: v1 and v2 QR invitations are unchanged. Older phones ignore the
  unknown `session.offer` type. No new phone capability name is advertised
  (older desktops reject unknown capability names), so the desktop sends the
  offer to any online linked phone and keeps the QR on screen.
- Extending to phone screen mirroring: add a `"screen"` entry with its own
  invitation parser to `SERVICES` on both sides plus vectors.

## (a) Linking: same Wi-Fi, six-digit comparison

**Implemented client-side** (no server change): the root code travels over the
local network instead of the camera, and a short comparison code replaces both
the QR scan and the 64-character fingerprint comparison.

1. On the main computer, **Phone → Add a device** starts
   `HostedController.lan_link_start` for five minutes (one phone per window, at
   most eight attempts). It answers UDP discovery on port 47390 only from
   RFC 1918 senders and runs one TCP handshake at a time on an ephemeral port.
2. On the phone, **Find my computer** broadcasts a query; the answer has only the
   computer's display name and TCP port.
3. Handshake ([lan_link.py](../src/orion_mini/lan_link.py), [LanLink.kt](../android/app/src/main/java/com/orionmini/mobile/LanLink.kt)):
   phone sends `H(ephemeral key ‖ nonce)`; the computer sends the signed root
   code, its ephemeral P-256 key and nonce; the phone reveals. Both derive
   `T = H(root code, commitment, both keys, both nonces)`, display six digits of
   `H(T)` and an ECDH/HKDF MAC key.
4. The phone shows **Check the code on your computer**. Only after the owner taps
   **Codes match** and passes screen-lock verification does it pin the root and
   create its keys (the unchanged `enroll`). It sends its signed request over the
   same connection, MAC'd with the transcript key, and also through Saiph Cloud
   as before.
5. The computer shows **<phone> wants to connect · 123 456**; **Codes match,
   approve** is enabled only after the authenticated request arrived. It calls
   the unchanged `approve`, so Windows Hello is still required and the roster is
   signed exactly as today.

If anything fails (firewall, different networks, no answer), the QR flow is on
the same screens.

## (c) Joining another computer: button, comparison, pop-up

**Implemented client-side** (owner request relayed by the coordinator, laptop case
L-SET-3; Ubuntu test L-NEW-4).

Before: the new computer pasted the main computer's root code from the phone QR
dialog, and the main computer approved through **Phone → Connect a phone**.

Now:

1. New computer: **Join as another computer** (one name everywhere: the wizard,
   Settings and the server error text). `HostedController.inspect_account_root`
   reads the account's first roster from Saiph Cloud (`/v1/devices/rosters/page`,
   existing API) and shows the main computer's security code. **Nothing is stored.**
2. The owner compares every group with the main computer (Settings → Saiph Cloud
   now shows "This computer's security code"; it is also under **Add a device**),
   ticks "Every group matches" and chooses **Trust and ask to join**.
   `join_account(fingerprint, confirmed)` re-reads the roster and pins the root
   only if its fingerprint is exactly the one displayed; a relay that swaps keys
   in between is refused and nothing is created. The paste-code path is kept
   under **Paste the main computer's code instead**, and its confirmation is now
   bound to the displayed fingerprint too (`trust_root_code(expected_fingerprint=…)`).
3. Main computer: a global pop-up (`DeviceApprovalPrompt`, any page, main computer
   only, paused while the Add a device wizard handles requests) shows **Approve a
   new device?** with "This is an unknown device at <approximate location>. Are you
   sure you want to approve this device?", the new device's security code, this
   computer's security code, a name field and an explicit match confirmation.
   **Approve** still goes through `approve()` with Windows Hello. **Deny** hides
   that request until it expires; **Block this device** refuses its device ID and
   signing key on this computer permanently (`blocked-devices.json`), including
   in `approve()`. One request is shown at a time with a count of the rest; more
   than three new devices in ten minutes adds a warning. Requests expire after
   five minutes (signed into the request code). Nothing is ever auto-approved.
4. Wording is device-neutral: **Add a device** on the Phone page and in Settings;
   the joining computer's copy points to the pop-up instead of Connect a phone.

Device names: approved devices no longer appear as "Main computer", "Device",
"Device". A member computer introduces itself to the main computer
(`device.hello`, sealed); the main computer shares the names its owner chose plus
the kind (phone/computer) with member computers (`device.labels`, accepted only
from the main computer, exact shape, ≤ 100 rows, names one printable line ≤ 40).
Settings lists each device as name + Main computer/Phone/Computer, and
**Send file to** shows "Pixel (phone)". Names are display-only and authorize
nothing; older apps ignore both message types.

Location: Saiph Cloud does not report where a request came from, so the pop-up
says "at an unknown location" and explains that a reported location would be
approximate and advisory. The UI already accepts a `location` string.

## Threat model

| Attacker | QR today | Six-digit LAN flow | Cloud session offer |
| --- | --- | --- | --- |
| Compromised Saiph account or malicious relay | Cannot forge root code (visual channel) | Not on the LAN channel; cannot add a device: the root signs only after the owner compares a code that the relay never sees, with Windows Hello | Sees ciphertext only; cannot create offers (needs a roster member's key); may delay or drop them (QR fallback) |
| Attacker on the same Wi-Fi | Cannot see the screen | One guess per attempt at the six digits (commit-then-reveal; 1 in 10⁶), ≤ 8 attempts per five-minute window the owner opened; cannot swap the request (MAC under ECDH key) | Can only reach the pinned TLS listener; the bearer secret is sealed to the phone |
| Both (account and LAN) | — | Still needs the owner to confirm matching codes on **both** screens; that is why the phone must confirm too (it pins the root) and the computer must confirm (it signs the roster) | As above |
| Stolen unlocked phone | Could scan | Could start linking only with access to the computer's open window and Windows Hello | Still needs the phone's screen lock, foreground and the computer's explicit start |
| A compromised linked computer | Already a roster member | — | Can offer a camera session; the phone still asks its owner and shows which computer asked |

Explicitly **not** done: auto-approval. A compromised account could otherwise
add a device that reads clipboard and notifications; every new device still
requires a code comparison and native owner verification on the main computer,
and existing roster-change alerts still fire on all devices.

## What would need a server change (proposal only, not deployed)

- **Approximate request location for the approval pop-up**: on
  `POST /v1/devices/approval-requests`, record a coarse, IP-derived
  `{"city", "region", "country"}` (no raw IP stored or returned), and return it
  with `GET /v1/devices/approval-requests` as
  `{"requests": [{"code": "...", "origin": {...}}]}` behind a version flag
  (today's strict client parser accepts only a list of strings, so the server must
  keep the old shape for old clients). The desktop would show it as
  "near <city, country> (approximate)"; it stays advisory, never a trust signal.
- **Server-side Deny/Block and rate limits**: `DELETE /v1/devices/approval-requests/{device}`
  and an account-scoped block list, plus a per-account cap on pending requests
  (e.g. 5 per 10 minutes). Today Deny/Block are enforced on the main computer.

- **Linking across different networks without a QR** (phone on mobile data):
  needs a relay rendezvous for *pending* devices, e.g. `POST/GET
  /v1/devices/link-sessions/{id}/messages`, a short-lived, size-limited,
  account-scoped mailbox carrying the same `link.*` messages. The comparison code
  keeps the relay out of the trust path. Today the sealed mailbox only accepts
  roster members.
- **"Phone sees the computer listed via the Cloud device list"**: the roster has
  no display names or device kinds by design; listing would need a signed,
  root-authored label field or the rendezvous above.
- **Push wake for offers**: the phone polls every 5 s while Saiph's sync service
  runs. A push hint for new sealed events would make camera requests reach a
  phone whose service was stopped.

## Physical acceptance checklist (coordinator)

Prerequisites: build the beta APK and desktop from this branch; the phone
(`adb -s RZCXA1J09ZL`) and computer on the same Wi-Fi; both signed in to the same
test account. Steps marked **(tap)** need a person; everything else can be driven
by `adb` and `scripts/desktop-ui.py` (see [TESTING.md](TESTING.md)).

Camera via Cloud (linked phone):
1. `adb -s RZCXA1J09ZL shell am start -n com.orionmini.mobile/.HostedActivity`; confirm Saiph Cloud is connected (`uiautomator dump`, look for "Connected").
2. Desktop: open Phone, click **Webcam**, then **Use phone as webcam** (desktop-ui click by name). Expect the status text "Sent to <phone>" and the QR.
3. Phone: within ~10 s `adb shell dumpsys notification --noredact | grep -A3 "Start camera for"` shows the notification (channel `orion_camera_requests`).
4. **(tap)** the notification; expect "<computer> wants to use this phone as its webcam" (`uiautomator dump`).
5. **(tap)** Start camera, **(tap)** screen-lock verification, allow camera permission if asked.
6. Desktop: status becomes Live; `camera.frame` reports frames. Stop on the desktop; the phone returns to idle.
7. Negative: start a session, wait 2 minutes without tapping; the notification disappears and tapping a stale one shows "That camera request expired".
8. Negative: tap **Send to <phone> again** twice, then accept one; the second offer must not start a second stream.
9. QR fallback: scan the QR on the same screen instead; unchanged behaviour.

Joining another computer (laptop case L-NEW-4, Ubuntu; needs a disposable or reset Saiph profile on the laptop):
1. Laptop: sign in with the test account, choose **Join as another computer**. Expect "Main computer's security code" and nothing created yet (`~/.local/share/.../hosted/` has no `root-pin.json`).
2. Main computer: Settings → Saiph Cloud shows "This computer's security code"; compare. **(person)** tick the match box on the laptop, **Trust and ask to join**.
3. Main computer: within 15 s the **Approve a new device?** pop-up appears on any page, with the unknown-device warning and both codes (desktop-ui screenshot). Compare the new device's code with the laptop.
4. Negative: **Deny** → the pop-up closes and does not return for that request; ask again from the laptop (Show a new request code) → it returns. **Block this device** on a second disposable profile → never shown again, also after restarting the main computer.
5. Approve: name it, tick, **Approve**, **Windows Hello (owner)**. Laptop becomes active; on both computers Settings lists "Desk · Main computer", "<laptop name> · Computer", "<phone> · Phone"; Send file to shows "(phone)/(computer)".
6. Paste fallback: on another fresh profile use **Paste the main computer's code instead**; a code from a different account is refused.

Linking without a QR (needs an unlinked phone profile or a disposable test account; do not reset the owner's phone):
1. Desktop (main computer): Phone → **Add a device**. Windows may ask to allow network access for Saiph; allow private networks.
2. Phone: Saiph → sign in → **Find my computer**. Expect "Check the code on your computer" with six digits.
3. Desktop shows "<phone> wants to connect" and the same six digits (screenshot via desktop-ui).
4. **(tap)** Codes match on the phone, **(tap)** screen-lock verification.
5. Desktop: **Codes match, approve** becomes enabled; click it; **Windows Hello** prompt (needs the owner).
6. Phone moves to Connected; desktop roster lists the phone; the security alert fires on other devices.
7. Negative: with the desktop window closed, Find my computer reports no computer; with a firewall block, the QR remains usable.
