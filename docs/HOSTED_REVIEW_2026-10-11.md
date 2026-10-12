# Hosted login, device approval and encryption — review

2026-10-11, branch `fix/product-reliability-2026-10-11`. A source review by the
product chat, not an independent security review. It records what exists, what a
user can reach, and what remains before any hosted feature can ship.

## Summary

The hosted pieces are **tested libraries and a separate development server, not
features**. Nothing outside the `hosted_*` desktop modules, the `Hosted*.kt`
Android files and their tests uses them:

- no desktop module or frontend screen imports `hosted_login`, `hosted_session`,
  `hosted_approval`, `hosted_transport`, `hosted_files` or `hosted_keys`;
- the ordinary Hub app does not mount `orion_hub.hosted` (it runs separately from
  `hosted_server.py` with its own database);
- no Android screen, service or worker references `HostedSession`,
  `HostedTrustStore`, `HostedRecipientKeys`, `HostedHttpTransport` or
  `HostedEnvelope`.

Every shipping feature (clipboard, notifications, SMS, calls, files, photos,
continuity) still travels through the self-hosted Hub's Link protocol, signed
with device P-256 keys over the mesh. The Hub can read those payloads. None of
them is covered by the hosted end-to-end encryption.

## What exists and looks sound

| Area | Component | Notes |
| --- | --- | --- |
| Native sign-in (desktop) | `hosted_login.py` | System browser, OAuth 2 authorization code with PKCE S256, fixed `127.0.0.1` loopback port with exclusive bind, constant-time `state` check, optional `iss` check, one exchange per attempt, code never logged, no ID token or offline scope |
| Token validation (server) | `hosted_auth.py` | RS256 only; `kid` pattern-checked; `jku`/`x5u`/`jwk`/`crit` headers refused; keys only from the fixed tenant JWKS; `iss`, `aud`, `sub` (single owner), `azp` (allowed native clients), `exp`/`iat` required; no leeway; generic 401 |
| Device approval | `hosted_approval.py` | Signed, canonical, domain-separated root and request codes, at most 10 minutes; the initial root pin needs a trusted code source or a full fingerprint match, never a server response; approval checks the server's pending candidate against the out-of-band request code |
| Mailbox access (server) | `hosted.py` | Account routes need the owner token; sealed routes need a device signature from a current-roster member, ±60 s timestamp and an atomic single-use nonce; device routes refuse cookies, `Origin` and bearer headers |
| Recipient encryption | `hosted_crypto.py`, `hosted_session.py`, `HostedEnvelope.kt`, `HostedSession.kt` | Tink HPKE (Python 1.16.1, Android 1.23.0) with keys separate from signing identities; envelopes bind deployment, roster version/hash, source, target, event and expiry |
| Key storage | `hosted_keys.py`, `HostedRecipientKeys.kt` | DPAPI (Windows) / Secret Service (Linux) / Android Keystore; owner-only DACL on Windows (elevated-token owner fixed on this branch); fails closed and preserves existing enrollment |
| Attachments | `hosted_files.py`, `hosted_blobs.py` | Streaming encryption, verify-before-publish, no overwrite, hard-link publication |

## Gaps before anything ships

1. **No user-reachable flow.** Sign-in, root setup, device approval (QR or code
   entry plus fingerprint comparison), revocation and recovery have no desktop or
   Android screens. Nothing calls these components.
2. **No Android sign-in.** `HostedHttpTransport` accepts an access token, but the
   app has no OAuth/PKCE flow (Custom Tabs/AppAuth) to obtain one.
3. **No session lifecycle.** Desktop login keeps no refresh token and no stored
   session, so every access-token expiry means a browser round trip. There is no
   sign-out, token revocation or account switch.
4. **Roster expiry versus availability.** Rosters default to 1 hour (24 h at
   most) and only the root device can renew them. No scheduler renews them, and
   the server refuses every device once the latest roster expires. Without
   automatic renewal on the root, all other devices lose mailbox access whenever
   the root is offline past the TTL. `RootApproval.renewal_due()` (added on this
   branch) reports when renewal is due; a root-side scheduler still has to call
   it and submit `renew()`. The root is a single point of failure; root transfer
   and lost-key recovery are documented non-goals.
5. **No feature transport integration.** Link event types, the clipboard/peer
   blob path, phone actions and file offers would need hosted envelopes, plus their
   own authorization, replay and recovery handling. A decrypted envelope must not
   dispatch a phone action by itself.
6. **Minor, operational.** Zero JWT leeway rejects tokens on a server whose
   clock runs ahead or behind; the hosted server needs synchronised time (NTP).
   Approval-code replay is already contained: `approve()` refuses any device ID
   ever present in roster history, and root codes only establish a pin.
7. **Unverified.** Physical-device acceptance, desktop↔Android interoperability on
   real devices and an independent security review have not been done.

## Contract notes for the hosting chat

The hosted server's routes are unchanged by this branch. Deploying
`orion_hub.hosted` gives a reachable development API only. It must not be
described as encrypting existing app traffic, and there is no client a user can
sign in with yet.
