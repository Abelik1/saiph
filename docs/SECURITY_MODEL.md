# Security model and current limits

Saiph separates device identity, account authorization and content encryption.
Their implementations and tests cover different boundaries; do not assume that
one successful component check establishes the security of every feature.

## Existing self-hosted operation

The ordinary Hub and app features use the existing P-256 device identities,
pairing, revocation and signed requests over a private Tailscale or Headscale
network. The ordinary Hub can process readable content. Private-network transport
encryption and signed requests do not prevent the Hub operator from reading that
content. Keep its listener private and protect its data and keys.

The desktop keeps identity, settings and pairing state in its private application
data directory, separate from installed releases. Enrollment invitations contain
private setup material. Never commit or publicly upload these files.

## Isolated hosted development components

`orion_hub.hosted` is a separate application with a separate database and a
single-customer deployment binding. Its routes handle account metadata, public
device rosters and sealed mailboxes. It does not mount the ordinary Hub's readable
feature routes. This is not a shared-tenant SaaS system.

Hosted account authorization validates configured Auth0 access tokens and fixed
issuer/audience/client/subject boundaries. Account login alone does not approve a
device or grant possession of content keys.

Recipient encryption uses maintained Tink HPKE components with keys separate from
P-256 signing identities. Signed routing context and encrypted payloads bind the
intended deployment, roster, devices, event and lifetime. A trusted root device
signs roster changes. Other devices need an independently verified root pin;
accepting a server-provided root after login is insufficient.

The client validates roster ancestry, signatures, membership, expiry and durable
generation state. Revocation, replay checks, bounded queues and delivery state
are separate controls. Root transfer and account-reset replacement of lost
content keys are not implemented recovery promises.

The server still observes account/device and routing metadata, sizes, timing and
availability. Encryption does not prevent traffic analysis, denial of service or
compromise of an authorized endpoint.

## What remains

An off-by-default development preview now connects native sign-in, approval
screens and encrypted clipboard text, notifications and explicit file/photo
sharing on desktop and Android. See [preview scope and acceptance](HOSTED_PREVIEW.md).
Physical-device acceptance, deployed Auth0/relay acceptance and independent
security review remain unfinished. Do not describe existing installed apps, ordinary Hub,
Seafile or Immich integrations as covered by the hosted prototype's encryption.
Do not dispatch phone actions solely because a low-level envelope decrypted;
active handlers need their own authorization, replay and recovery integration.

Use synthetic data for development and consult [SECURITY.md](../SECURITY.md) for
private reporting. Hosted production readiness requires those integration gates
and review; component tests do not replace them.
