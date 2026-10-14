# Hosted integration plan

Follows [the hosted review](HOSTED_REVIEW_2026-10-11.md). The components exist and
are tested; this is the order in which to turn them into a feature a user can
reach, and the decisions needed first. Steps 1-6 now have opt-in preview source
on `feat/hosted-user-flow`; their real-device exit checks remain open. See
[implementation and acceptance status](HOSTED_PREVIEW.md).

## Decisions needed from the owner

1. **Which device is root.** The root alone signs rosters and must renew them
   before expiry. The desktop is the natural root (always on, has DPAPI); a phone
   root is more portable but sleeps. Root transfer is not implemented.
2. **Roster lifetime and renewal margin.** Default 1 h (maximum 24 h). Longer
   means devices survive a root that is offline longer; shorter bounds how long a
   withheld revocation can be replayed by the server. Suggested: 12 h lifetime,
   renew when 4 h remain.
3. **Auth0 native clients.** Register an Android native client (Custom Tabs,
   app-link or custom-scheme redirect) alongside the desktop loopback client;
   decide session length and whether refresh tokens (rotating, with reuse
   detection) are allowed.
4. **Which features move first.** Suggested: clipboard text, then notifications,
   then files/photos (attachments already exist). SMS and call commands last,
   because they need their own authorization and replay rules. (2026-10-14: the
   owner approved texts and calls; root-only actions behind a phone-side opt-in,
   see `src/orion_mini/hosted_features.py`.)
5. **Coexistence.** Whether a device can be paired to a self-hosted Hub and a
   hosted deployment at once, and which wins for each feature.

## Build order

| Step | Desktop | Android | Server | Exit check |
| --- | --- | --- | --- | --- |
| 1. Sign-in and session | Settings screen calls `hosted_login`; DPAPI-protected refresh token if allowed; sign-out clears it | AppAuth/Custom Tabs flow; Keystore-protected token | none | sign in, restart, sign out, expired-token path |
| 2. Root setup | Create root keys (`hosted_keys`), `initialize_root`, show root code as QR plus full fingerprint | none | genesis admission | fresh deployment with one root |
| 3. Device approval | Scan or paste the request code, compare the fingerprint, `approve()`; revoke screen | Scan the root QR or compare the full fingerprint (`trust_root_code`), generate a request code, submit enrollment | candidate and admission routes (exist) | approve and revoke a phone; refusal paths |
| 4. Roster renewal | Scheduler: `renewal_due()` → `renew()` → submit; catch-up after downtime | Handle expiry gracefully: stop sending, show "waiting for root" | none | root offline beyond the lifetime, then recovery |
| 5. First feature | Clipboard over `hosted_transport` with existing echo/repeat rules | Same through `HostedSession` | sealed events (exist) | physical repeat/echo/Wi-Fi-loss cases |
| 6. More features | Notifications, files/photos via `hosted_files` | Same | blobs (exist) | per-feature acceptance |
| 7. Review | Independent security review of steps 1–6 before any paid or public use | | | written findings closed |

Each step keeps self-hosted operation unchanged and ships behind a setting that
is off by default until its exit check passes on real devices.
