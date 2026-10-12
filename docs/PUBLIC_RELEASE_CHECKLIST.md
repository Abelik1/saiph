# Public source publication

Public source, signed binaries, hosted service activation and paid billing are
separate approvals. Completing this checklist does not authorize any deployment.

## Freeze the intended source

- Review the exact source tree and retain a SHA-256 inventory outside the source
  tree or in a manifest that excludes its own hash. Preserve licences, upstream
  attribution and component boundaries.
- Include contribution, security-reporting and community policies. Check that
  linked development instructions work without maintainer credentials.
- Review screenshots, binaries, embedded metadata, commit messages and author
  identities as well as text files. Contributor names/emails and DCO trailers
  become public; choose the intended identity before committing.
- Keep runtime state, real provider settings, enrollment files, private operations
  records and credentials outside the product. `.gitignore` does not remove
  anything already committed.

## Review the complete history that would become public

Use a separate audit clone. Fetch all branches, tags and relevant pull-request
refs before checking; `--history` checks locally fetched refs, not GitHub by itself.

```text
python scripts/public-release/check-public-data.py --history
gitleaks dir . --config .gitleaks.toml --redact --no-banner
gitleaks git . --log-opts=--all --config .gitleaks.toml --redact --no-banner
```

The identifier check is a narrow fingerprint regression guard, not a complete
personal-data or credential scanner. Independently review private identifiers
using the maintainer's private inventory. Scanner exceptions must be exact,
reviewed synthetic fixtures. Keep detailed scan evidence private.

If sensitive history exists, keep that repository private. Deleting current
files or creating an orphan branch in the same GitHub repository does not clear
other refs, pull requests or cached views. Prepare a reviewed clean source import
in a separate repository, or coordinate a complete history cleanup before
changing visibility. A source-only export must exclude `.git`, nested Git
directories, private refs and ignored local files. Do not use `git push --mirror`
from the private repository to seed a public one.

Revoke or rotate any actual exposed credential before attempting history cleanup.
GitHub's [sensitive-data removal guidance](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)
explains the additional handling required for cached views and pull-request refs.

## Prepare GitHub for outside contributors

- Require maintainer review, DCO and relevant CI checks on the default branch;
  protect workflow, signing and security-sensitive changes.
- Enable private vulnerability reporting and test the route in SECURITY.md.
  Enable available secret scanning/push protection and security notifications.
- Keep fork pull requests on unprivileged hosted runners with read-only tokens
  and no production secrets. Do not run untrusted PR code in privileged
  `pull_request_target` jobs or on maintainer machines.
- Keep signing and deployment in separately protected maintainer workflows with
  reviewed environments. Review existing releases, Actions logs/artifacts,
  issue/PR bodies and attachments before making an existing repository public.
- Confirm repository visibility only after reviewing the final source/history
  receipts. Re-run the checks whenever the candidate changes. The owner performs
  or explicitly approves the publication step.
