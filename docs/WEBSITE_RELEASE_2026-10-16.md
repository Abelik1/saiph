# Landing-page release, 16 October 2026

The compact home page keeps the interactive device graphic, places platform
downloads immediately after it, promotes Firebase for Android, highlights Hosted,
and adds an Account button on every page. Analytics is enabled for the approved
public landing origins; local previews and account/private routes stay excluded.
The technical analytics status is confined to the privacy notice. A sourced
Apple Continuity / Microsoft Phone Link / Saiph comparison follows pricing.

## Hosted feature correction

The earlier comparison inherited the README's outdated "Coming" labels. Hosted
texts and call controls were merged in `80623fb` and included in the beta.5
release and later beta.7 desktop / Android 0.9.2 catalog. This was checked against
the released source ancestry and the private operations release records; no
owner settings or private deployment identifiers are copied here.

The website and README now describe one-to-one SMS replies, new texts, call
alerts, answer/decline and dialing as included in the Hosted beta, gated by the
phone's opt-in and Android permissions. This is not evidence of physical-device
acceptance, which remains pending. Notification replies, automatic image
clipboard sync, MMS pictures and group replies remain Hosted implementation
gaps. Call audio stays on the phone. These are not intended subscription tiers.

## Pricing

This publication retains €3.99/month and €36/year so it agrees with the current
account checkout validation. The owner's requested €9.99/month and €89.99/year
change is prepared separately for a coordinated account/Stripe release; this
landing publication does not activate it or migrate existing subscriptions.

## Validation

Windows / Python 3.12.10 / Node 24.18.0, isolated worktree, TEMP/TMP and caches:

- `python -m pytest tests/test_website_release.py tests/test_website_downloads.py
  tests/test_public_release_metadata.py tests/test_release_readiness.py
  tests/test_website_analytics.py -q --basetemp build/landing-release-pytest-confirmed
  -o cache_dir=build/landing-release-cache`: 221 passed, 1 skipped (Windows
  directory-symlink privilege). The Python executable is the isolated
  `build/compact-landing-check/venv/Scripts/python.exe` in the parent checkout.
- `python scripts/public-release/build-website.py --settings
  website/landing-settings.json --output build/landing-preview-final`: 16 static
  files prepared. Production injects the existing protected trader address;
  synthetic checks and screenshots contain no owner address.
- `node build/landing-publish/browser-release.cjs` from the parent checkout:
  passed at 1440, 1024, 768, 390 and 320 px; graphic tabs, Account/Firebase links,
  existing prices, Hosted feature labels, table/sources, and header/page fit.
  No provider requests or page errors occurred in local checks.
- `scripts/public-release/check-public-data.py` and `git diff --check` passed.

The initial isolated pytest run lacked the `build/` parent for its temporary
directory (164 passed, 58 setup errors); creating the build output corrected
setup, followed by the clean full run above. No desktop/Android binary, Hosted
service, account billing configuration or live payment was changed by this
website-only release. Live publication and analytics acceptance are verified
separately after deployment.
