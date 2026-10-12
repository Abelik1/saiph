# Friends beta onboarding fixes, 12 October 2026

These changes prepare friends to use their own accounts, invitation codes and
packaged connection settings. They do not enable subscriptions.

- The account site's public `/setup` guide explains installation, desktop root
  approval, Android permissions and the current feature limits.
- Account pages use a fresh Content Security Policy nonce on every request,
  including framework scripts. Production aliases redirect to the configured
  account origin. Authentication callback parameters and POST bodies are never
  forwarded from aliases. Protected preview deployments retain their own origin.
- Android beta builds with packaged defaults hide manual deployment fields behind
  advanced settings. Permission buttons open the relevant Android settings;
  they do not grant access automatically.
- New Linux credential-directory ancestors use mode 0700 individually. Previously
  `mkdir(parents=True)` created intermediate directories with the process umask,
  causing first-use credential storage to reject its own group-writable parent.
  Fresh profile and transfer directories also request private permissions.
  Existing insecure directories and symlinks remain rejected without repair.

Local evidence: Python 3.12, Node 24, disposable synthetic profiles. Account build,
46 unit tests, owner-sandbox production HTTP checks and friends-beta production
HTTP checks passed. The latter verifies actual Next/SDK session handling, CSP
nonces, canonical redirects, redemption isolation, CSRF checks and download
authorization with a synthetic backend. The setup guide rendered in a browser
with no captured errors or warnings. Credential/runtime/distribution/download
regressions passed (91 passed, 8 platform-specific skips). The final exported
desktop suite passed with private temporary directories (1036 passed, 28 skipped).
Frontend unit tests passed (78 tests); the frontend production build passed. The default
group-writable umask made file-transfer fixtures fail their existing permission
checks; those fixtures require private temporary directories. Dedicated new
credential regressions explicitly use umask 0002.

Android compilation, native installer builds, actual provider login, live download
catalog contents, independent security review and physical-device acceptance
remain unverified in this laptop session. Do not infer those from local tests.
Deployment details and the desktop completion handover belong in private operations.
