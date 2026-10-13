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

Do Not Disturb is shared across paired devices: turning it on or off on the
phone, in Windows or GNOME, or with the Phone page toggle quiets the others, and
the newest change wins. Saiph reads Windows Do Not Disturb but never changes it;
on Windows it quiets Saiph's own notifications. On Android it uses Saiph's own
Do Not Disturb rule, which needs Do Not Disturb access. Android 15 and later may
not let Saiph end Do Not Disturb you started on the phone; end it there. Turn sync off in Settings →
Advanced on the computer or Settings on the phone. Physical-device acceptance
is pending.

**Photo to computer** on the phone's home screen takes a photo with your camera
app and sends it to a paired computer, where it is saved in Downloads → Orion
and placed on the clipboard with a "ready to paste" notification. Only image
files up to 32 MB from that phone's own request are placed on the clipboard.
Document scanning with edge correction is not included yet.

To get a computer online through your phone, join the phone's hotspot once in
the computer's Wi-Fi settings, then choose it under Settings → Advanced → Phone
hotspot. **Connect** joins it in one click; with automatic reconnection on,
Saiph joins it when the Hub has been unreachable for 30 seconds and the computer
has no other network. Wi-Fi passwords stay with Windows or NetworkManager.
Android doesn't let apps switch the hotspot on, so **Hotspot settings** in the
phone app opens the right Android page.

**Phone remote** turns your phone into a remote for apps on a computer. Turn it
on in Settings → Advanced → Phone remote on the computer, choose which phones may
use it, and choose the apps offered: media, presentations, web video, locking the
computer, and typing into the app in front. Lock and typing are off unless you
turn them on. On the phone, open **Remote for computer apps**, pick the computer
and an app, and use its buttons or text box. Presentation and video controls
work only when that app is in front on the computer. Wayland does not allow apps
to send keys, so only media controls work there. See the
[security model](SECURITY_MODEL.md#phone-remote-control) before enabling typing.

From the Phone page and the tray's Phone menu you can also:

- control music or video playing on the phone (needs notification access);
- start a new text message, with suggestions from the phone's contacts. Contact
  results are kept only in the computer's memory for a few minutes and are never
  stored on the Hub;
- switch the phone between ring, vibrate and silent (silent needs Do Not
  Disturb access on the phone);
- call a number from the Calls tab; the call is placed on the phone and its
  audio stays there. Codes containing * or # are refused, because they can change
  phone settings such as call forwarding. Recent calls appear on request and are
  not stored on the Hub;
- lock a computer from the phone's home screen or the Lock computer quick
  setting, after allowing the phone in that computer's Phone remote settings and
  turning on This computer.

**Send to phone:** in File Explorer choose Send to → Saiph (phone); in GNOME
Files use Scripts → Send to phone (Saiph); in Dolphin use the Send to phone
(Saiph) action. Saiph asks which phone and confirms before sending; at most 20
files, each up to 2 GB. The tray's Phone menu also has Send a file to phone.

**New screenshots and photos:** when you take a screenshot or photo on the phone,
the computer shows a notice with Copy (it lands on the clipboard) and Save (to
Downloads → Orion). Nothing transfers until you choose one. Turn it off with
Offer new screenshots and photos in Settings → Advanced.

**Pictures in messages (MMS):** conversations show Show picture for MMS parts.
The picture is fetched from the phone only then, kept in Saiph's own folder,
shown in the conversation, and saved to Downloads → Orion on request.

**Group conversations:** with an up-to-date Saiph on the phone, you can reply to
group conversations from the computer; replies are sent as MMS.

**Phone apps in their own windows:** the Apps tab lists the phone's apps and opens
one in its own window through scrcpy; Pin adds it to the Start menu or the
applications menu. It needs authorised wireless or USB debugging (as the phone
preview does) and Android 10 or later.

**Your devices on the phone:** the phone's home screen lists your other devices
with their battery. Computers with a battery share it every minute or when it
changes. From there you can **Ring** a computer to find it (it plays an alert for
up to 30 seconds with a Stop window; switch it off with Let my phone ring this
computer) and **Lock** it if you allowed that in Phone remote.

**Sketch to computer:** draw on the phone, or mark up a photo, and it arrives on
the computer's clipboard ready to paste.

**Touchpad:** the phone remote's Touchpad adapter (off by default) turns the phone
into a touchpad with click, right-click, double-click and scrolling, alongside the
typing text box. Windows and X11 only.

**Lock when my phone leaves (Linux):** in Settings → Advanced, choose your
Bluetooth-paired phone; the session locks once it has been gone for the chosen
time. It never unlocks. On Windows, use Dynamic Lock in sign-in options instead.

Smaller conveniences, each with a switch in Settings → Advanced:

- **Verification codes:** a phone notification containing a one-time code shows
  **Copy code** on the computer. Automatic copying is off unless you turn it on.
- **Ring your phone:** the Phone page rings an online phone at alarm volume for
  up to 30 seconds; tap the phone's notification to stop it.
- **Low battery:** the computer tells you once when a phone drops to 20% and is
  not charging.
- **Calls pause media:** music or video playing on the computer pauses while the
  phone rings or is in a call, and only what was playing resumes afterwards. On
  Linux this needs playerctl; on Windows the optional WinRT media binding.

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
