# Public export

The private source repository produces a fresh tree with `scripts/export-public.py`.
Its TOML manifest lists every source file and destination explicitly. Unlisted files,
Git history, Workspace implementation, runtime data and owner deployment settings are
never copied. A new output path is required; existing directories are never overwritten.

The exporter first writes a staging directory, applies reviewed projections and SPDX
headers, then checks private identifiers, credential/configuration filenames, Firebase
configuration, mesh literals and Python/frontend imports. Gitleaks is mandatory, and
the export is only made visible at the requested path after both scans pass. Failed
staging trees are removed. `PUBLIC_EXPORT.json` records file hashes and scan results.

Reviewed projections remove Workspace-only Python popup/job implementations and the
frontend's lazy Workspace import, select Link in source checkouts, and retain the Link
cases from mixed-edition tests. Companion executable discovery is exported under
`companion_tools.py`; the private `tools.py` name remains in the private checkout.
The public Python dependency manifest omits private transcription dependencies.
Source files in the private checkout are not modified by export.

UTF-8 text is exported with LF line endings and no byte-order mark, so Windows
and Linux checkouts of the same reviewed source produce the same file hashes.
Binary assets retain their exact bytes. Manifest destinations are checked without
case sensitivity to prevent collisions on Windows. Relative frontend imports and
documentation links must stay within the exported tree. Git worktree pointers,
environment-file variants and reparse points are rejected alongside Git history.

Mesh security code and its synthetic tests necessarily contain mesh addresses. Each
approved literal is listed against its exact exported path in `mesh_examples`; there
are no directory-wide exceptions. Real owner addresses are replaced with synthetic
examples by explicit per-file replacements before scanning. Any additional literal,
including another literal in an approved file, fails. The protocol CIDR is likewise
an explicit per-file exception. This inventory is private because the scrub mapping
must not disclose original owner values.

The exported tree must then pass its desktop/Hub/frontend tests and build the Link
edition on its target operating system. A scan result alone is not release approval.
Deskflow source, setup controls and TLS supervisor are public and optional; upstream
Deskflow is installed separately and sharing is off until explicitly enabled. No
physical keyboard/mouse, Android or multi-day acceptance is implied by unit tests.


The canonical product also runs `check-public-data.py` on tracked source to
reject private course/person fixtures and an owner-specific delegate identity.
Run it with `--history` against the exact source ancestry intended for publication.
It reports file paths and commit IDs without echoing matching data. A clean current
tree does not sanitize earlier commits. Existing private development history must
remain private until the publication-history gate is explicitly resolved; do not
rewrite or publish that history as a side effect of this check. Ordinary secret
scans and the private exporter's broader owner-data rules remain required.
