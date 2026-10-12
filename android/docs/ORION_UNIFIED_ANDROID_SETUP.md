# Independent Android enrollment

Approach: retain Saiph's existing package, P-256 Android Keystore key, one-use pairing claim,
signed Hub updater and Link bus. An invitation supplies the Hub address; setup guides the
official Tailscale application and Android VPN consent. There is no embedded VPN, new
identity, shared mesh credential or Saiph account. Already paired phones refuse incoming
invitations rather than silently changing their trusted server.

## Invitation contract

The existing `orion://pair?v=1&hub=...&code=...` QR/link remains valid. An optional
`mesh_login_server` query supplies an explicit HTTPS controller origin. Omitting it means
standard Tailscale; an independent installation never defaults to the owner's Headscale.

The private `.orion-enrollment` JSON is bounded to 16 KiB:

```json
{
  "format": "orion-enrollment",
  "version": 1,
  "hub": "http://100.100.10.2:8765",
  "code": "12345678",
  "expires_at": "2026-10-08T12:10:00Z",
  "mesh_login_server": null
}
```

These are synthetic examples. Treat real invitations as private, short-lived credentials.
The optional controller field may be absent for compatibility. Unknown/duplicate keys,
expired files, public/LAN Hub addresses, embedded credentials and origin paths are rejected.
Allowed numeric mesh ranges are `100.64.0.0/10` and `fd7a:115c:a1e0::/48`, unprivileged
ports 1024–65535, default 8765. Public builds have no legacy hostname shortcut or default Hub. Existing custom origins survive upgrade independently
of the old migration marker; invalid saved origins fail closed.

## One-time flow

1. Scan an invitation QR or choose **Open invitation** in Saiph. Confirm **Use invitation**
   only for a server whose owner you trust.
2. Saiph offers **Install Tailscale** or **Open Tailscale**. Install the official app, sign
   in to the server's mesh and accept Android's VPN consent. Return to Saiph.
3. If the invitation specifies a custom provider, **Advanced setup** gives the server URL
   and copy action. In Tailscale open Settings → Accounts → three-dot menu → Use an alternate
   server, then follow that provider's web sign-in. Saiph cannot silently configure it.
4. Saiph retries pairing automatically while the invitation is valid. The pending invitation
   stays in app-private preferences; success removes it and commits Hub origin plus device ID
   together. A failed claim never replaces an existing configuration. QR invitations have a
   local ten-minute retry ceiling; the server's one-use code and expiry remain authoritative.
5. Finish setup freely. Notification, SMS/call/photo, battery and clipboard permissions can
   be granted later; optional permissions never block **Finish setup**.

Networking details appear in Advanced. Install/sign-in and OS permission actions are
one-time setup. Normal operation reconnects without Connect, Refresh or Sync buttons.

The Android home screen keeps Settings at the top, outside the scrolling inbox. Permission
setup keeps **Back to Saiph** and **Settings** visible while scrolling; Android Back also
leaves setup. Leaving defers the unfinished checklist without marking it complete and
does not reopen it merely because the app resumes. **Finish setup** remains available
independently. Granted (and partially granted message/call) permissions offer **Manage**,
which opens the appropriate Android settings for review or revocation. Saiph does not
claim it can revoke runtime, special-access or debugging permissions itself. Buttons
retain a minimum 48 dp touch target.
The app uses charcoal surfaces and blue/cyan actions, matching the desktop palette.

Permission revocation is also enforced by the service. Returning to Saiph immediately
refreshes advertised capabilities and feature registrations; the background poll refreshes
them even while disconnected. Outbound publications and reconnect retries recheck current
access, dropping queued SMS/call/photo/notification frames after access is lost. Regranting
SMS access starts a fresh conversation reconciliation. Cached photo blobs recheck access
to their original MediaStore URI before serving, including changes to selected-photo access;
revoking all photo access removes their temporary offers. Explicit SAF file-sharing grants
remain independent. Notification actions require both a connected listener and current OS
listener access. An unfinished but deferred checklist does not reopen from status-notification
taps; those go to Settings. Revocation cannot recall content already accepted by the Hub
or delivered to another paired device. Physical Samsung revocation/regrant checks remain pending.
If Android's broader All files access is still granted, it also permits reading photos;
the photo Manage action opens that special-access page so it can be reviewed or revoked.

Official references: [Android install/consent](https://tailscale.com/docs/install/android),
[Headscale's Android alternate-server steps](https://headscale.net/stable/usage/connect/android/),
and [Tailscale's published navigation handler](https://github.com/tailscale/tailscale-android/blob/main/android/src/main/java/com/tailscale/ipn/ui/util/DeepLinkNavigator.kt).
The navigation handler does not expose an action that applies a custom controller.

## Transport and independent builds

Android network-security XML cannot express mesh CIDRs. Cleartext transport is enabled
at the platform level; active Saiph Hub HTTP/WebSocket and direct clipboard/file paths
gate numeric mesh origins at runtime and disable redirects. Direct peer gates do not use
DNS resolution for untrusted names. Tailscale supplies encryption. Encrypted-backup targets
also require numeric mesh addresses; no public HTTP fallback is introduced.

Build independent APKs with `-PorionFirebase=false`. This explicitly ignores any owner
`google-services.json` present locally; do not copy that private file to a friend. The
public default also disables Firebase. Hub update checks, signed
APK download, SHA-256 verification and Android package-signature enforcement continue
without Firebase. The existing application ID and release signer must remain unchanged
for data-preserving updates. Version code/signing configuration are untouched by this change.

Keep each deployment's release manifest private on its Hub and supply the exact matching
GPL Android source and existing upstream notices with distributed binaries. Desktop/Hub
private licensing is outside this Android fork's GPL scope.

## Verification limits

Pure JVM tests cover enrollment parsing, mesh boundaries, IPv6 URLs, hostile origins,
legacy QR compatibility, custom controller validation and private pending expiry. Isolated
instrumentation fixtures cover preserving a friend's Hub/identity through migration and
refusing already paired claims without HTTP. Local build/lint checks must also pass with
Firebase explicitly disabled. No real phone, VPN enrollment, release publication or live
server change is performed by this source-only work. A fresh friend phone still needs the
guided-install, VPN-consent, actual pairing and no-Firebase Hub-update acceptance checks.
