# Combined Saiph repository

Desktop and Android are developed in this one repository, with one issue tracker
and pull request workflow. Android is a separate application and build, rather
than code embedded into the desktop executable. Orion identifiers remain stable.

| Directory | Purpose | Licence |
| --- | --- | --- |
| `src/`, `frontend/`, `assets/` | Windows and Linux desktop Link | AGPL-3.0-or-later |
| `hub/` | Self-hosted Hub and encrypted hosted runtime | AGPL-3.0-or-later |
| `android/` | Android application, including retained upstream source | GPL-3.0-only; component notices apply |
| `sdk/` | Integration SDK | MIT |
| `account-web/` | Owner-only development account website | AGPL-3.0-or-later |
| `website/`, `scripts/`, `docs/` | Website, packaging and product documentation | AGPL-3.0-or-later; third-party notices apply |

Read the component licence files and retained upstream notices. A single Git
repository does not change any component's licence. Root DCO sign-off checks
apply to all contributions. DCO does not transfer copyright or grant additional
relicensing rights. Commercial distribution remains subject to each licence.

This repository is private during preparation. It was imported using reviewed
file inventories with fresh history; personal Workspace implementation, private
deployment settings, runtime state, credentials and original Git histories were
excluded. `PUBLIC_EXPORT.json` records the initial imported source snapshot,
including combined-source scans. Its hashes describe that snapshot, not later
commits. Before a source release, produce a fresh reviewed inventory and scan the
entire current tree and Git history; do not reuse stale passing receipts.

Account website application code belongs in `account-web/`. Private service
deployment, account administration, billing provider configuration and infrastructure
settings belong in the separate private `saiph-cloud` operations repository.
That repository deploys a pinned revision of the Hub here; it must not maintain a
second implementation of the hosted application. Secrets remain outside both.

Make product fixes here, and operational fixes in the operations repository.
Original internal checkouts are retained as archives and for private Workspace
development; changes there do not automatically update this repository.

Public visibility, signed releases, website deployment and commercial Hosted
launch are separate steps. Preparation does not authorize publication or hosting
unreviewed user data.
