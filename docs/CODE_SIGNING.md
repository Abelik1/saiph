# Code signing policy

Signing is not yet configured. Current CI artifacts are unsigned development
previews. No certificate publisher or signing-provider sponsorship is claimed.

The maintainer controls official releases. Future signing will require a reviewed
public source revision, successful checks, a verified CI build origin and explicit
maintainer approval for each release. Untrusted pull-request jobs receive no signing
credentials. Only project-authored Windows executables and installers will be
signed under the project's policy; upstream components retain their own identity.

Before enabling signing, publish the actual certificate publisher, approvers,
reviewers and contributor roles with links to the responsible public accounts.
Require multi-factor authentication and protected release permissions. Record the
approved certificate fingerprint independently of the release files and update
that policy through review when the provider rotates certificates. Signing requests
must enforce product name `Saiph` and the exact release product version.

Final Windows releases must pass the [release verification](RELEASING.md), including
trusted embedded Authenticode, expected publisher and certificate, timestamp,
version metadata and Windows SDK SignTool. Checksums describe the final signed
bytes and exact public source commit. Signing does not establish clean-machine
compatibility, security review, or SmartScreen reputation.

Saiph connects to a Hub selected by the person configuring it. Phone permissions,
device approval and optional integrations affect which data is shared; see the
[security model](SECURITY_MODEL.md). A future signing-provider application must
describe the actual shipping network/privacy behavior and the applicable external
services. This document does not claim that all processing stays on the desktop.

SignPath Foundation is the chosen provider, but the project has not been accepted.
Its [current terms](https://signpath.org/terms.html) require reviewed project
eligibility, specific team roles, release approval and policy disclosures. Add its
required acknowledgement only after acceptance. An application draft, the release
workflow or an unsigned preview does not establish acceptance or a signed release.

## Provider decision (2026-10-11, maintainer: individual in Ireland)

Checked against the providers' own pages on 2026-10-11. Recheck before applying,
because eligibility and prices change.

| Option | Eligible today? | Cost | Publisher shown | CI fit |
|---|---|---|---|---|
| [Azure Artifact Signing](https://learn.microsoft.com/en-us/azure/artifact-signing/quickstart) (formerly Trusted Signing) | **No.** Public Trust is available to organizations in the EU, but individual developers must be in the US or Canada | Basic about USD 9.99/month (third-party listings; confirm on Azure pricing) | Validated organization | Best: OIDC from GitHub Actions, no key handling |
| [SignPath Foundation](https://signpath.org/terms.html) | **Probably, once the public repository and a released build exist.** OSI licence (AGPL qualifies), no proprietary code, automated verifiable builds, MFA, named roles, per-release manual approval, "verifiable reputation" for executables, discretionary acceptance | Free | SignPath Foundation (not Saiph or the maintainer) | Good: official GitHub Action, HSM keys, build-origin checks |
| [Certum Open Source Code Signing](https://shop.certum.eu/open-source-code-signing-on-simplysign.html) (SimplySign cloud) | **Yes.** Issued to an individual as "Open Source Developer, NAME" | From EUR 49 (cloud; listed out of stock on 2026-10-11) or EUR 69 (card and reader). Validity capped at 459 days from 2026-02-27 | Maintainer's name | Weak: SimplySign needs a phone-generated one-time code, so unattended CI signing means storing a TOTP seed or signing on an attended runner |

**Recommendation:** apply to SignPath Foundation as soon as the clean public
repository and a first unsigned public preview exist. It is free, keeps keys out
of CI, and already matches this policy (build origin, manual approval, product
metadata). The release workflow below is wired for it.

**Fallback:** if SignPath declines or the timeline is too slow, buy the Certum open
source certificate and sign on an attended Windows machine or a protected
self-hosted runner. That needs a separate signing step; do not store the
SimplySign seed in GitHub secrets. **Azure** becomes the best option only if Saiph
is run through a registered company (an Irish company is eligible).

Points to raise with SignPath before applying:
- The signed Link build contains only AGPL/MIT project code. The optional private
  Workspace add-on is installed separately, is never in the signed bundle, and is
  not offered as a commercially licensed edition of the same code.
- Saiph Hosted is a paid service. Explain that the signed desktop is fully usable
  self-hosted and that Hosted is opt-in and off by default.
- The privacy disclosure must name Hosted, the website account, Stripe and Auth0
  as the external services the app or site can contact.

## Release workflow

[`.github/workflows/release-windows.yml`](../.github/workflows/release-windows.yml)
runs only when the maintainer starts it on `main`. It stops immediately unless
every value below is set. In order, it:

1. builds Link with `scripts/build-native.py`, which already writes `ProductName`
   `Saiph` and the exact `ProductVersion` that SignPath enforces;
2. uploads `dist/OrionMini/` and requests a signature for `OrionMini.exe` only
   ([`docs/signing/signpath-app.xml`](signing/signpath-app.xml));
3. accepts the returned bundle only if `OrionMini.exe` is the single changed file
   (`scripts/public-release/check-signed-bundle.py`);
4. packages that signed bundle into the installer, so `package-manifest.json`
   hashes the signed executable;
5. requests a signature for the finished installer
   ([`docs/signing/signpath-installer.xml`](signing/signpath-installer.xml)). The
   installer finds its payload just before the Authenticode certificate table,
   and the builder aligns it so signing adds no padding;
6. verifies both signatures, publisher, certificate fingerprint, timestamp and
   version with `verify-windows-signatures.py`, then writes checksums and evidence
   marked `signed-candidate`.

Each signing request waits up to an hour for a maintainer to approve it in SignPath.

Maintainer setup after acceptance:
- GitHub environment `windows-signing`: required reviewer = maintainer, deployment
  branch = `main` only, secret `SIGNPATH_API_TOKEN`.
- Repository variables: `SIGNPATH_ORGANIZATION_ID`, `SIGNPATH_PROJECT_SLUG`,
  `SIGNPATH_SIGNING_POLICY_SLUG`, `SIGNPATH_APP_CONFIGURATION`,
  `SIGNPATH_INSTALLER_CONFIGURATION`, `SAIPH_SIGNING_PUBLISHER` (exact certificate
  subject) and `SAIPH_SIGNING_CERTIFICATE_SHA256` (lowercase SHA-256 of the
  certificate). Take the last two from SignPath's published certificate, not
  from a signed file.
- In SignPath: the two artifact configurations from `docs/signing/`, a release
  signing policy with manual approval, and MFA for every team member.
- Then publish the roles, the SignPath acknowledgement and the privacy statement
  on the home and download pages, as the terms require.
