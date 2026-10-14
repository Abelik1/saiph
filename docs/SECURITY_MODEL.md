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

### Phone commands from a computer

A paired computer can ask the phone to play or pause media, change the ringer
mode, send a text to a new number and place a call. Each needs the matching
Android permission and is refused by the Hub unless the phone advertises it.
Dialing accepts ordinary numbers only: codes with * or # are refused on the
computer, the Hub and the phone, because MMI codes can change settings such as
call forwarding. Contact search results and call history answer one computer's
request; the Hub relays them without storing them, and the computer keeps them
in memory for a few minutes.

### Phone remote control

Phone remote lets an approved paired phone press fixed controls on a computer:
media keys, presentation and web-video keys, locking the computer, and
(separately opted in) typing text into the app in front. It is off by default.
The computer's owner turns it on, chooses which phones may use it and which
adapters are offered. Each control maps to one predefined key press or system
action; there is no shell, no raw key code and no screen sharing. Presentation
and video keys are sent only when a recognised presenter or browser is in front.
Typed text is limited to 500 printable characters on one line, touchpad movement
to 2000 pixels per command, and commands are rate-limited per phone (touchpad
movement has its own budget). The touchpad, like typing, is off by default. Wayland sessions cannot receive generated keys.

The computer trusts the sending device identity that the Hub attaches to each
event, as it does for other Link commands. A compromised Hub or a stolen,
unrevoked phone can therefore press the enabled controls. Keep the lock and
typing adapters off unless you trust both, and revoke a lost phone promptly.
Windows does not let Saiph send input to elevated windows.

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

### Hosted texts and calls

Texts, call state, contact results and call history travel inside the same
sealed envelopes as clipboard text; the event type is inside the ciphertext, so
the hosted service relays them without seeing message text, numbers, names or
which kind of event it carries. No server change was needed. What the server can
still learn is traffic shape: a burst of events while conversations sync, a
quicker desktop poll once a phone shares texts or calls, and event timing that
can correlate with incoming texts and calls.

Each sealed event has exactly one recipient. The phone sends its capabilities
to every other approved device; each computer answers with `phone.subscribe`
and its display name, renewed about every two minutes and kept by the phone for
ten. Live text updates and call state are copied to every current subscriber.
A full conversation sync goes only to the computer that asked for it, and
contact results, call history and refusals go only to the requesting computer.
The roster does not record device kinds: any approved device that subscribes
is treated as a computer and receives the phone's texts and call state.

Decryption proves which approved device sent an event, not that it may act. A
phone carries out a text reply, a new text, answering or declining a call,
dialing, a contact search or a call-history request only when all of these hold:
the sender is a current roster member that subscribed in the last ten minutes
(root or not), the phone's owner turned on Texts and calls in Saiph Hosted (off
by default, confirmed with the screen lock), the matching Android permission is
granted, the payload has the exact shape and limits of its type, and, for a
text, a call answer or decline or a dial, the event's receipt has not been
claimed before (each runs at most once; an interrupted one is not retried).
Replies go only to one-person threads; dialing refuses `*` and `#`.

Several computers can act on the same call. The phone settles it first come,
first served: it carries out the first answer or decline for a ringing call,
immediately sends `call.handled` (which action, which computer) to every
subscribed computer so they stop ringing, and answers any later answer or
decline for that call with `call.refused`, shown on the losing computer as
"Answered on <computer>" or "Already handled on another computer". A dial is
refused while the phone is on a call or placed another call in the last ten
seconds. A call declined from a computer is reported as ended, not missed. The
computer's name in these messages is chosen by that computer and is not
authenticated beyond its roster membership.

Each computer sends an action only to an approved phone that advertised the
capability and was heard from in the last five minutes, and checks that a reply
thread exists and a call is still ringing. It shows phone data only from
approved devices that advertised the matching capability; contact results,
call history and refusals are accepted only within a minute of that computer's
own request and are kept in memory. Revoking a phone deletes its texts and calls
from the computer that revokes it (today, the root); the phone stops sending to
a revoked computer at its next roster refresh.

Anyone who controls an approved computer while it is unlocked, or its hosted
keys, can read the phone's synced texts and act on them within these limits,
just as with clipboard and notifications. A lost computer should be revoked
from the account and the phone's Texts and calls switch turned off until then.
The desktop app can currently only be the root; a second computer cannot yet
join an account, so the multi-computer path is implemented in the protocol and
on the phone and tested with synthetic devices only.

## What remains

An off-by-default development preview now connects native sign-in, approval
screens and encrypted clipboard text, notifications, explicit file/photo
sharing and (opt-in on the phone) texts and calls on desktop and Android. See
[preview scope and acceptance](HOSTED_PREVIEW.md) and the
[friends beta scope](HOSTED_FRIENDS_BETA.md#scope-and-remaining-gates); texts
and calls have unit tests only.
Physical-device acceptance, deployed Auth0/relay acceptance and independent
security review remain unfinished. Do not describe existing installed apps, ordinary Hub,
Seafile or Immich integrations as covered by the hosted prototype's encryption.
Do not dispatch phone actions solely because a low-level envelope decrypted;
active handlers need their own authorization, replay and recovery integration.

Use synthetic data for development and consult [SECURITY.md](../SECURITY.md) for
private reporting. Hosted production readiness requires those integration gates
and review; component tests do not replace them.
