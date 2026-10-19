# Files over the local network

Saiph Cloud's relay holds encrypted file blobs of at most 20 MiB (19.9 MB of file
after the sealed stream's overhead), with a small per-deployment quota and four
pending blobs per recipient (`hub/orion_hub/hosted_blobs.py`). Raising those limits
means running a bigger relay. Instead, when two of the owner's approved devices
share a private network, a file of any size up to 1 TiB goes directly between
them, and Saiph Cloud only carries the one-use invitation. A file up to 19.9 MB
still goes through Saiph Cloud when the direct path does not work.

The design reuses the phone camera's local trust ([PHONE_CAMERA.md](PHONE_CAMERA.md))
and the QR-less session offers ([QRLESS_CONNECT.md](QRLESS_CONNECT.md)): a sealed
`session.offer` with service `"file"`.

## Who listens

The computer always listens; phones only connect, as for the phone camera and the
phone screen. So:

| Direction          | Listener              | Offer                                        |
|--------------------|-----------------------|----------------------------------------------|
| computer → computer | sender                | `file` offer, mode `get`                    |
| computer → phone    | computer (sender)     | `file` offer, mode `get`                    |
| phone → computer    | computer (receiver)   | phone sends `file.lan.request`; computer answers with a `file` offer, mode `put` |

## Messages (all inside sealed Cloud envelopes)

- `session.offer` (session_offer.py, `SessionOffer.kt`) with `"service": "file"` and
  an `orion-file:1:` invitation: base64url JSON with exactly
  `session, addresses, port, certificate, secret, expires` (the camera's fields:
  private literal IPv4 only, SHA-256 of a fresh self-signed certificate, a 256-bit
  bearer secret; the offer format allows 120 s and senders use 100 s, so a receiver
  whose clock is a little behind still accepts it) plus `mode` (`get` | `put`), `name` (at most 255
  UTF-8 bytes, no path, control character or reserved Windows name), `size`
  (0 to 2^40), `sha256` and `request` (empty for `get`, the phone's request ID for
  `put`).
- `file.lan.request` `{type, version: 1, id, name, size, sha256, expires_at}`: a
  phone asks one computer for an upload invitation.
- `session.refuse` `{type, version: 1, id, reason}`, reason `unreachable`,
  `storage` or `busy`: the receiver cannot use an offer (or request), so the sender
  falls back at once instead of waiting.
- `session.close` (unchanged format): the sender withdraws an offer it gave up on;
  a phone also uses it for a `put` invitation it could not reach.

`android/app/src/test/resources/session-offer-vectors.json` (the `file …` cases) and
`lan-file-vectors.json` (names, requests, refusals) are read by both test suites.

## The listener (lan_files.py)

One transfer is one TLS 1.2+ listener on an ephemeral port with its own certificate
(valid 24 hours, so a slow transfer can still reconnect):

    POST /file/<session>/claim     Authorization: Bearer <secret>  -> {"resume": token}
    GET  /file/<session>           Authorization: Resume <token>, Range: bytes=N-   (get)
    POST /file/<session>/done      {"size", "sha256"}: the receiver's own result     (get)
    GET  /file/<session>/received  -> {"received": N}                                (put)
    PUT  /file/<session>?offset=N  the rest of the file; answered after verification (put)

- The client checks the certificate's SHA-256 against the invitation before it sends
  the secret. The secret is spent by the first successful claim, before the reply: a
  replayed offer or a second device gets 403. Only the claimant learns the resume
  token, over the pinned connection.
- A dropped connection may reconnect with the token and continue from the last byte
  for 90 s (`RESUME_SECONDS`). A newer connection replaces an older one. After that
  the transfer fails on both sides with a message and the sender offers Retry.
- Both ends hash the stream. The sender counts a `get` file as sent only after the
  receiver's `done` reports the exact size and SHA-256; a computer accepts a `put`
  only if its own hash matches the request. A mismatch deletes the copy.
- An unclaimed invitation expires after 100 s; nothing listens afterwards.

## Sending (hosted_transfers.py, LanFiles.kt)

1. If the computer has a private IPv4 address and the name is valid, the file is
   hashed and offered directly (state "Connecting to … on your network").
2. The recipient connects at once (no prompt). Progress shows on both sides.
3. If the recipient refuses, cannot connect or does not answer within 30 s (45 s for
   a phone waiting on a computer), the sender withdraws the offer. A file up to
   19.9 MB then goes through Saiph Cloud exactly as before; a larger one fails with
   "… didn't answer on your network. Saiph Cloud sends files up to 19.9 MB and this
   file is N MB, so both devices must be on the same Wi-Fi or network with Saiph
   open." Without any private address a large file is refused before anything is
   sent.
4. While a direct offer waits, the desktop polls Saiph Cloud every 4 s for the answer.

Devices without this feature ignore the offer or request, so the sender falls back
after the wait; nothing else changes for them.

## Receiving

A receiver acts without a tap because the owner started the send on their own
approved device and the sealed envelope proves which one. It checks free space
first (size + 64 MiB; otherwise `storage`), fetches into a private folder
(desktop: `<profile>/hosted/incoming`, Android: `noBackupFilesDir/lan-files`) and
shows the file with **Save** once verified. Save moves it to Downloads → Saiph
(Windows Known Folder / `XDG_DOWNLOAD_DIR`; Android MediaStore) without overwriting;
Android also keeps **Save as…**. Unsaved files are removed after 30 minutes on the
desktop, on Dismiss, on sign-out and at the next start. At most eight (desktop) or
four (phone) transfers arrive at once; more are refused as `busy`.

## Windows Firewall across updates

Windows Firewall allows or blocks inbound connections by the full path of the
listening program, and remembers the owner's answer to its prompt as rules for
that path. An installed Saiph runs from
`%LOCALAPPDATA%\Programs\OrionMini\releases\<version>\app\saiph.exe`, a new path
after every update. Found on the owner's PC (2026-10-19): allow rules named
"saiph.exe" existed only for beta.14 to beta.32, so after each update the phone
camera, phone screen and direct file transfers needed a new approval, or were
silently blocked when the prompt was missed or cancelled.

A per-user installer cannot add firewall rules (that needs administrator rights),
and a stable launcher alone does not help, because the rule must name the program
that listens. So:

- **A relay at one fixed path.** The package contains `SaiphNetwork.exe`
  (`scripts/packaging/WindowsNetworkRelay.cs`, file description "Saiph local
  network"). The installer copies it to `%LOCALAPPDATA%\Programs\OrionMini\SaiphNetwork.exe`
  on every install (same path, replaced only when the bytes change; a copy still
  running keeps the previous one, which works the same) and removes it on uninstall
  if it is byte-for-byte one that a release shipped.
- **Saiph listens on 127.0.0.1** for the phone camera, phone screen and file
  transfers, and starts the relay per session (`lan_relay.listen`). The relay
  listens on a free port on all IPv4 interfaces, copies bytes to the loopback
  listener and exits with the session or with Saiph. It never sees inside the
  pinned TLS connection. Windows asks about "Saiph local network" once; the answer
  keeps applying after updates. Source runs, Linux and installs without the relay
  listen directly, as before; a relay that does not start falls back to that too.
- **A clear notice when Windows blocks it.** Saiph reads (never changes) the
  firewall rules for the relay's path with `Get-NetFirewallApplicationFilter` and
  the current network category. If a block rule applies (for example the prompt
  was cancelled), or the Wi-Fi is marked Public while Saiph is allowed only on
  private networks, Settings → Saiph Cloud says so with **Open firewall settings**
  (Windows Security's "Allow an app through firewall" page), and a large send that
  the other device could not connect to says the same instead of the generic text.

Not covered: the nearby-phone discovery used by Add a device (UDP 47390,
`lan_link.py`) still listens in saiph.exe itself. `SaiphNetwork.exe` is compiled
during packaging and is not Authenticode-signed yet (like `Uninstall.exe`), so the
firewall prompt shows an unknown publisher; signing it means adding it to the
SignPath configuration (owner step). The owner's old per-version rules stay in
place and can be removed in Windows Security; they do no harm.

## What is not covered

- Both devices must reach each other on a private IPv4 network (same Wi-Fi/LAN, no
  client isolation). Windows asks once to allow Saiph on private networks if the
  phone camera never did.
- A transfer interrupted for more than 90 s, or by quitting either app, starts again
  from the beginning with Retry.
- Photo originals from the phone gallery still use Saiph Cloud and its 19.9 MB limit.
- This is development work: unit and loopback tests only. Physical acceptance on
  real Wi-Fi and an independent security review are still required
  ([RELEASE_STATUS.md](RELEASE_STATUS.md)).
