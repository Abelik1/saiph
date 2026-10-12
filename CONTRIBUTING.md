# Contributing to Saiph

Contributions to the desktop app, Hub, Android app, SDK and websites are welcome.
One issue tracker and pull-request process covers this repository. Please follow
the [code of conduct](CODE_OF_CONDUCT.md).

## Choose a change

For bugs, describe the affected version, operating systems, reproduction steps,
expected behavior and actual behavior. Use synthetic examples. Small fixes can
come directly as a pull request; discuss substantial features or architectural
changes in an issue before implementing them.

Report security vulnerabilities privately using [SECURITY.md](SECURITY.md), not
in public issues or pull requests. Never attach real messages, screenshots of
personal content, logs containing bodies, tokens, passwords, Firebase
configuration, databases, device/signing keys or enrollment invitations. Removing
a file in a later commit does not remove it from history. If you accidentally
commit a secret, stop pushing and report it privately; revoke or rotate it before
coordinating history cleanup.

## Fork, develop and submit

1. Fork the repository on GitHub and clone your fork. Add this repository as an
   `upstream` remote if you want to fetch later changes.
2. Create a focused branch from the current default branch. Keep unrelated work
   in separate pull requests.
3. Use a virtual environment and isolated app profiles, temporary data and build
   caches. Tests must not contact a real account, deploy a service, or alter an
   installed app or paired device without explicit coordination.
4. Make the smallest complete change and run the relevant checks below. Add a
   regression test when it can demonstrate the bug or protect a security boundary.
5. Sign off every commit with `git commit -s`. Before committing, review
   `git diff --cached` for secrets and personal data.
6. Push your branch to your fork and open a pull request against this repository's
   default branch. Describe the problem, resulting behavior, related issue,
   validation commands/results and remaining limitations. Use synthetic images
   for UI changes.

Maintainers review outside contributions and may request changes. Address review
comments on the same branch; sign off any new or amended commits. Passing CI
does not guarantee a merge or grant access to releases, signing or deployment.

Commit author names, email addresses and DCO trailers become public. Choose your
identity before committing; a verified GitHub noreply address can protect your
personal email. Use the same name/email for your author identity and sign-off.
Never sign off for another person.

## Development and checks

Use Python 3.12 for desktop/Hub work and Node 24 for JavaScript applications.
Create and activate a Python virtual environment before installing dependencies.

| Area | Setup and checks |
| --- | --- |
| Desktop Python | `python -m pip install -e ".[dev,hosted]" -r hub/requirements-hosted.txt httpx`, then `python scripts/public-release/verify-public.py` |
| Desktop frontend | `npm --prefix frontend ci`, then `npm --prefix frontend run test:unit` |
| Hub | Install `hub/requirements-hosted.txt`, pytest and httpx; run `PYTHONPATH=hub python -m pytest hub/tests -q`. On PowerShell, set `$env:PYTHONPATH='hub'` before running `python -m pytest hub/tests -q` |
| Account website | From `account-web/`, run `npm ci --ignore-scripts`, `npm test`, `npm run typecheck` and `npm run build`; follow its [local integration instructions](account-web/README.md) for affected HTTP/database behavior |
| Android | Follow [android/README.MD](android/README.MD), [Android contribution guidance](android/CONTRIBUTING.md) and the independent build/test commands in [Android CI](.github/workflows/android.yml); use isolated caches, synthetic data and relevant JVM/lint checks |
| Packaging | For affected desktop distribution code, run `python scripts/build-native.py --profile link` on the actual target OS and follow [release validation](docs/RELEASING.md) |

Linux Qt/WebEngine requires system libraries listed in
[public CI](.github/workflows/public-ci.yml). Component READMEs and CI define
additional prerequisites. Work on one component does not require operating
someone else's hosted service or using maintainer credentials.

Run `python scripts/public-release/check-public-data.py` and review your complete
commit range. CI also scans source/history for credentials, checks DCO sign-offs,
and runs component/dependency checks. Scanner exceptions must name exact reviewed
synthetic fixtures; do not exclude entire test directories or bypass failing
security checks.

Record the platform and exact commands you ran, including failures and skips.
Keep unit, container, emulator, physical-device and multi-day evidence separate.
A passing unit test does not prove successful installation, upgrades, encryption
of every shipping feature, or stability on another person's devices.

## Compatibility and scope

Preserve internal Orion identifiers, application IDs, data paths, signing
identity compatibility, pairing, revocation and supported networking components.
Changes to permissions, authentication, device trust, crypto, updates or data
handling need explicit review and reproducible evidence. Retain upstream credits
and licence notices.

Private Workspace implementation, production settings and operations stay outside
this product repository. Official signing and deployment are maintainer tasks;
pull-request checks must work without production secrets. See the
[repository layout](docs/REPOSITORY_LAYOUT.md) and
[release status](docs/RELEASE_STATUS.md).

## Contribution licence and DCO

Contributions use the licence of the files changed: AGPL-3.0-or-later for the app,
Hub and websites, GPL-3.0-only for `android/`, MIT for `sdk/`, and the retained
upstream licence for third-party files. Copyright remains with the contributor.

Every commit must carry your genuine sign-off certifying the
[Developer Certificate of Origin 1.1](DCO.txt). Use `git commit -s`; signing off
certifies origin and rights, does not transfer copyright, and grants no separate
relicensing right. DCO is distinct from cryptographically signing a commit.
Commercial sale and hosting remain subject to the applicable open-source licence
obligations.

Public pull-request CI checks each commit for a sign-off matching its author.
Maintainers must require that DCO check and the relevant CI checks in branch
protection, with maintainer review before merge.
