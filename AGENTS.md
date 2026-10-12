# Saiph product work

This is the canonical product repository for desktop, Hub, Android, SDK and website.
Keep Android under `android/` with its GPL licence and upstream credits. Keep the
MIT SDK and AGPL app/Hub boundaries. Preserve internal Orion identifiers, pairing,
application IDs, data paths and signing identity compatibility.

Infrastructure settings and service operations belong in the private operations
repository. Do not copy owner settings, keys, databases or original private history
here. Use synthetic fixtures. DCO sign off your own commits.

Build and test with isolated profiles/caches; do not install apps, operate physical
devices or disrupt an owner's running tests without coordinating first. Follow
`CONTRIBUTING.md`, component build instructions and `docs/RELEASE_STATUS.md`.
Record checks accurately; hosted encryption, signing, physical acceptance and
independent security review must not be inferred from unit tests.
