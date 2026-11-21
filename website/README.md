# Saiph website

For marketing-page reviews and changes, use **Page-CRO (`page-cro`) as the lead
skill** and read [the shared conversion brief and required workflow](../docs/LANDING_CONVERSION.md#required-skill-and-workflow-for-marketing-page-work)
first. This guidance applies to Claude and Codex. Keep the deliberate compact
page and clear primary action; use Impeccable for supporting visual/accessibility
checks and Copywriting for focused messaging. Device setup guidance belongs in
the account site and apps.

All public pages share a compact header (Features, Self-host, Download, Account) and footer
(Downloads, Self-host, Privacy & terms, Contact, Cookie settings). Keep launch
updates and source links in relevant download/self-host content instead of
repeating them in global navigation.

The checked build assembles `privacy.html` as the policy home with Website
privacy, Account privacy, Terms and Refunds tabs. Edit policy text in its existing
source document; `consolidate_legal_pages` composes those documents at build time
to avoid divergent copies. The old account-privacy, terms and refunds URLs ship
as noindexed aliases with fragment-preserving navigation and a plain-link
fallback. `assets/legal.js` enhances the canonical page with keyboard/history
support; all four documents are readable without JavaScript and printable.
Contact remains separate so the protected trader address stays only in its
noindexed page. Always preview generated output, not raw source pages.

Static product source. The product and operations repositories are private;
source publication, downloads and Hosted availability are separate launch gates.
The prepared new offer is 14 days free with a card required, then €9.99/month
unless cancelled. Release the website/account changes together after the
[trial activation checks](../docs/CARD_REQUIRED_TRIAL.md); earlier no-card trials
keep their original terms.
Vercel visit analytics (pageviews, allow-listed campaign tags and four button
counts) is enabled in `landing-settings.json`; local previews remain untracked.
`robots.txt`, `sitemap.xml`, canonical and link-preview tags and the share image
`assets/og-image.png` (rendered from `scripts/public-release/og-image.html`) are
checked by `tests/test_website_seo.py`. No email collector
or payment integration is active here. See [analytics activation](ANALYTICS.md).

Build a checked local preview from this worktree (Python 3.12):

```powershell
python scripts/public-release/build-website.py --settings website/preview-settings.json --output build/site-preview
python -m http.server 8099 --bind 127.0.0.1 --directory build/site-preview
```

The preview config keeps unavailable links disabled. Publish the generated output,
not the raw website directory. The builder uses an explicit file allowlist,
validates local references and writes a content-hash manifest. It never deploys.

Before a public release, operations must verify the actual private GitHub release
metadata and each versioned Windows, Linux, Android and server artifact, its
checksum, signature where required, and release approval. Do not invent artifact
URLs or expose private release links on a public page. Supply real links in a
public-fields-only JSON settings file and use `--mode launch`. The builder checks
link syntax; remote availability and signature verification need separate evidence.

Tally is the selected signup processor. Before enabling `waitlistUrl`, complete
and approve the privacy notice.
Set `waitlistPrivacyUrl` and a visible `waitlistNotice` explaining email use before
collection. Review controller/contact, retention, deletion, processor location and
transfers, consent/withdrawal and access/security. No example notice is a legal
approval. Keep collection disabled until those decisions are reviewed. The privacy link may point to the local draft notice while signup is disabled.

Saiph Cloud subscriptions opened on 15 October 2026. `subscribeUrl` points to the
account site's `/account` page, where people sign in and choose a plan; checkout
never runs on these static pages. Set it together with `hostedPrice` (a euro
amount such as `€9.99`), `hostedPeriod` and an optional short `hostedPriceNote`.
The builder rejects any other subscription link, a price without a link, or a
link without a price. With the link empty the pages fall back to beta access or
the email list. Keep claims aligned with
[the security model](../docs/SECURITY_MODEL.md): Hosted is a beta service without
an independent security review yet. Texts and call controls are included in the
released beta builds and require phone opt-in and Android permissions; physical
acceptance remains pending. Saiph Cloud and a self-hosted Hub share the same
features; the only difference is starting the webcam from the phone, which needs
Saiph Cloud's sealed delivery (self-hosted phones scan the computer's code).

The trader's postal address is required on the contact page but is not kept in
Git. The hosting project sets `SAIPH_TRADER_ADDRESS` (one plain line, for example
`1 Example Street, Town, A00 B000`); the builder escapes it and writes it only into
`contact.html`, which is marked `noindex`. Without it the page says the address is
available on request, and `--mode launch` refuses to build.

Website changes belong in their own product worktree/branch. Hand operations the
signed-off commit, validation evidence and hostname decision. Do not change the
hosting runtime pin merely to consume a website-only commit.

## Informational landing page

`landing-settings.json` links the public product repository and sends Subscribe buttons to the account site. It enables no release downloads or waitlist collection. Publishing these static pages does not publish either Git repository or launch Hosted. Use the builder in preview mode for this informational deployment; full launch validation remains stricter.

The comparison below downloads and pricing uses Apple's and Microsoft's linked
support documentation, checked 16 October 2026. Recheck those sources before
changing its claims. Saiph entries follow the current feature split in the root
README and Hosted page; implementation-only additions are excluded. Keep the
Hosted implementation gaps and the phone-only call-audio limit visible.


## Release downloads, waitlist and privacy

`downloads.html`, `waitlist.html` and `privacy.html` share the product styling and
remain informative with no release downloads or signup enabled. Tally is selected,
and the public controller identity is approved. The public controller contact has
not been confirmed; support email setup is deferred and the notice stays draft.
No personal forwarding destination belongs here.

Copy `launch-settings.template.json` to protected operations configuration and
complete only public fields. Privacy approval requires the working controller
contact, hosting retention/transfers and actual contact-mail processing details.
Collection also requires processor/location/transfer details, retention/deletion,
identical visible consent text, the published form's single opt-in controls and
disabled email tracking. The reviewed form is `https://tally.so/r/gDy42K`; the only
allowed query is `?consent_version=NOTICE_VERSION`, exactly matching
`waitlist.noticeVersion`. Required email and consent, disabled partial submissions,
and no respondent confirmation email are the reported form settings. There is no
double opt-in. A Boolean does not configure an external provider; verify the actual
form and campaign controls before activation. Keep `waitlistUrl` empty, privacy
`status` draft, and `contactEmail` empty until the controller contact is confirmed.
The template's notice version is a preparation value, not privacy approval.
See [LAUNCH.md](LAUNCH.md).

Generate candidate download settings from actual downloaded release assets:

```powershell
python scripts/public-release/prepare-website-downloads.py --repository Abelik1/saiph --release-json build/release.json --platform-map build/platform-map.json --artifacts build/release-assets --source-commit FULL_COMMIT_SHA --output build/download-settings.json
```

Inputs are a GitHub REST release response, four platform-to-real-filename entries,
and all release files with `SHA256SUMS` and `release-source.json`. The tool checks
local bytes, exact source/checksum metadata, GitHub upload state/size/SHA-256
digests and the fixed repository/tag URLs, then emits public settings only. It
does not fetch, build, sign, upload, publish or infer source-publication approval.
Review and merge those fields into launch settings only after release acceptance.
The builder enforces the same source/tag contract and rejects private downloads.

Run the offline website/release checks with Python 3.12:

```powershell
python -m pytest tests/test_website_release.py tests/test_website_downloads.py tests/test_public_release_metadata.py tests/test_release_readiness.py -q
```

## Android beta invite

Set `androidBetaUrl` to the Firebase App Distribution invite link for the outside
tester group (`https://appdistribution.firebase.dev/i/...`; create it in the Firebase
console under App Distribution > Invite links). The home and downloads pages then
use Firebase as the primary Android install button; with the field empty the
button stays disabled. The standalone APK is a secondary link.
The builder accepts only that link shape. The invite page is Google's: it collects the
tester's email, and the privacy page says so. Remove the link or disable it in the
console to close beta signups.

## Legal/privacy preparation bundle

Draft website/account privacy, Hosted terms, refund/withdrawal and contact pages
are prepared. Read [the legal review record](../docs/LEGAL_PRIVACY.md) and the proposed
retention schedule before approving any public collection or paid service. The
public contact and provider/retention facts remain unconfirmed. The draft pages
and passing source checks do not establish legal or Stripe approval.

## Native Android callback

The static bundle includes `/.well-known/assetlinks.json` for the existing friends-beta certificate and `android/oauth2redirect.html`. The root `vercel.json` rewrites the exact extensionless callback internally, sets no-store/no-referrer and a hash-pinned script CSP. The fallback loads no assets or analytics and clears query/fragment from browser history. It never relays a code to a custom scheme. Keep callback headers and the script hash in sync; test the actual deployed response and Android domain association before distributing a build that requests HTTPS. The existing beta signer is not a production-signing assertion. Hosting still handles the incoming request; this static source does not establish provider log-retention behavior.
