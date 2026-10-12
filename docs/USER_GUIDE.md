# Using Saiph Link

Saiph Link contains **Phone**, **Cloud** and **Settings**. Start with the
[self-hosted server guide](ORION_SELF_HOSTED_SERVER.md). You need a reachable Hub,
a Windows or Linux desktop, and the separately maintained Android app. Hosted is
planned; these instructions do not create a hosted account.
Beta testers can follow the step-by-step [beta tester setup guide](BETA_TESTER_GUIDE.md).

## Pair your devices

Install and configure your private Tailscale or Headscale network using its own
official tools. Keep the Hub reachable only within that network. Use the Hub's
enrollment flow to add your desktop and phone; open the resulting
`.orion-enrollment` invitation with Saiph. Invitations are private credentials:
never put them in an issue or share them publicly.

Once the computer is paired, open **Phone → Add a device → Show pairing QR**
and scan it with **Scan pairing QR** in the Android app. The private QR works
once and closes on expiry or when a new device appears. Use **Close** when
finished; closing hides the QR but does not revoke the invitation before it
expires. **Save invitation file** keeps the `.orion-enrollment` file flow for
another computer. Keep QR images and invitation files private. If no computer is
paired yet, use the server enrollment flow described in the self-hosted guide.

In Settings, confirm that the expected Hub and devices are connected. On Android,
grant the permissions needed for each enabled feature. Notification access,
clipboard access, SMS, camera and microphone have different OS restrictions;
enabling one permission does not guarantee every feature works on that phone.

## Everyday use

Phone shows the paired phone's available information and controls. Begin with a
synthetic notification and clipboard text. Review the target device before sending
a file, phone action or message. Only enable camera/microphone functions when you
intend to use them, and stop capture when finished.

Cloud connects to separately configured services; it does not automatically
provision storage. Optional tools and services should not block basic phone
pairing. Deskflow is optional and requires a separate installation; see the
[Deskflow integration guide](ORION_DESKFLOW.md).

Settings holds device and Hub configuration, feature controls and update status.
Saiph's public name changed from Orion; package IDs, data directories, service
names, pairing identities and invitation formats retain compatible Orion names.
An update should preserve existing pairing and startup preferences.

## Troubleshooting and privacy

Check that the private network is connected, the Hub is reachable, the devices
are still admitted and Android permissions/background settings allow the feature.
Restart affected components before changing keys or pairing identities. Do not
delete an existing data directory as a generic repair step.

The existing self-hosted Hub can process readable content. Network encryption and
device signatures do not make every feature end-to-end encrypted. See the
[security model](SECURITY_MODEL.md) before choosing where to run it.

Report ordinary bugs with the version, OS/phone model, reproducible synthetic
steps and sanitized metadata. Follow [SECURITY.md](../SECURITY.md) for private
vulnerability reports. Never attach messages, tokens, keys or personal databases.
