# Contributing to Saiph Android

Use synthetic data and preserve upstream copyright and licence notices.
Never commit Firebase configuration, enrollment invitations, keystores, device
keys, personal messages or screenshots. Changes to permissions, device approval,
identity, networking or updates need security review and reproducible checks.

Contributions use the licence of the files changed. The Android app retains its
upstream GPL licence; separately licensed components retain their original terms.
Copyright remains with contributors. DCO adds no restriction on commercial sale
or hosting and grants no extra right to relicense contributions under proprietary terms.

Each commit must include your genuine `Signed-off-by: Name <email>` trailer.
Use `git commit -s` to certify the [Developer Certificate of Origin 1.1](DCO.txt),
with a name and email you are entitled to publish. Do not sign for anyone else.

Follow the build instructions in [README.MD](README.MD). Run the relevant JVM
unit tests and lint for a change. State separately which checks ran on an emulator
or physical device; a source build is not proof of a successful phone upgrade.

Public pull requests will require the DCO check. Maintainers must enable that
check in branch protection when the repository is transferred and made public.
