# SDK and plugin scope

`sdk/python/orion_client.py` is MIT-licensed and preserves the `orion.api/v1`
reporting contract used by compatible local hosts. Its Python client uses the
standard library and reports status/events without making a tool depend on the
desktop being available.

The public Saiph Link edition does not include personal Workspace plugin
management, command execution, calendar or assistant pages. Shipping the SDK
does not mean that those features are present in Link. A compatible host must
register a tool before it can accept that tool's reporting endpoints. Do not
invent a Link extension workflow around the retained SDK.

The historical local protocol discovers the host from its local `api.json`,
uses a bearer token on loopback, refuses browser-origin requests, and can queue
reports in the local inbox when a compatible host is closed. That discovery
file and token are private runtime state and must never be distributed.

Treat reported content as data. Any future public plugin host must present
commands, paths and permissions for review before execution, preserve finite
request limits and avoid exposing the loopback API on a public network.


Paired Link installations create **no delegate grants**. Pairing alone does not
permit an assistant or other agent to read phone data. Trusted owner tooling may
explicitly call the broker with a `delegate_grants` mapping in its Hub configuration
(or an explicit mapping argument), for example `{"reader": ["inbox.read"]}`.
Every name and scope is validated before any grant is issued; an empty mapping
issues nothing. This is an owner configuration interface, not a Link UI setting.
Grant files are private bearer credentials. The scoped CLI requires an explicit
`--credential` file and never selects an owner-specific credential automatically.
Existing grants retain their existing expiry/revocation rules; removing a local
configuration does not revoke a previously issued grant on the Hub.
