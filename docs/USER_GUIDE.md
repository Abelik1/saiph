# Using Saiph Link

Saiph Link contains **Phone**, **Cloud** and **Settings**. By default Saiph
connects through a **Saiph account**: Saiph runs the connection, so you need only
the desktop and Android apps, with no server and no Tailscale or other network
software on your phone or computer. Saiph accounts are in an invite-only beta; these
instructions do not create one.

Self-hosting is optional and only for people who choose it during setup. It
needs a reachable Hub on your own private network; see the
[self-hosted server guide](ORION_SELF_HOSTED_SERVER.md) and the step-by-step
[self-hosting beta guide](SELF_HOSTING_BETA_GUIDE.md).

## Install and first-run setup

The Windows installer asks, before installing, whether Saiph should start when you
sign in, add "Saiph (phone)" to File Explorer's Send to menu, and open when setup
finishes. The Linux `.run` asks the same about start-up and the GNOME Files and
Dolphin "Send to phone" actions. On an update the choices start from what is
installed now; unticking one removes only what Saiph added.

When Saiph opens for the first time, **Phone** shows a **Connect your phone**
wizard, with one task on each screen:

1. **Sign in to Saiph** with the account you use on your phone. New beta testers
   activate their invitation on their account page first.
2. Choose **Set up this computer** to make it your main computer, which approves
   your other devices. If you already have a main computer, expand **Already use
   Saiph on another computer?** to join it instead.
3. Open Saiph on your phone, sign in with the same account and scan the QR shown
   in the desktop's Phone tab. Compare every group of the computer's security
   code when the phone asks. The desktop moves on to approval by itself once
   the phone has scanned; **Continue to approval** is there if it does not.
4. The phone's request appears on the approval screen. Choose **Review and approve**,
   compare every group of its security code with the phone, give it a name and
   approve it. **Back to scanning** returns to the QR if needed and clears any
   previous comparison. The desktop then waits for the phone to connect, tells
   you when it has, and **Done** opens the normal Phone page.

The security codes are fingerprints of the devices' encryption keys. Sign-in
finds your account; the comparisons check which devices you are trusting.
**Can't scan? Copy a code instead** and **My device hasn't appeared** contain
manual fallbacks. They still require the full security-code checks.

Add another phone from **Phone → Connect a phone**. Until a phone is connected,
Settings → General also has a **Connect a phone** shortcut to this flow. The
**Optional setup guide** in that section covers feature choices, optional tools
and privacy preferences; on a connected computer it starts at the feature
choices, and it does not interrupt first connection. Its **Set up later** action
closes it.

Choose **Use my own Hub instead** only if you manage your own server. Use its
private invitation to connect this computer, then scan its phone pairing QR.

## Self-hosting: pair your devices

This section applies only if you chose **I self-host my own Hub**. Saiph account
users skip it. Install and configure your private Tailscale or Headscale network using its own
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
Connections on the computer or Settings on the phone. Physical-device acceptance
is pending.

**Photo to computer** on the phone's home screen takes a photo with your camera
app and sends it to a paired computer, where it is saved in Downloads → Orion
and placed on the clipboard with a "ready to paste" notification. Only image
files up to 32 MB from that phone's own request are placed on the clipboard.
Document scanning with edge correction is not included yet.

To get a computer online through your phone, join the phone's hotspot once in
the computer's Wi-Fi settings, then choose it under Settings → Connections → Phone
hotspot. **Connect** joins it in one click; with automatic reconnection on,
Saiph joins it when the Hub has been unreachable for 30 seconds and the computer
has no other network. Wi-Fi passwords stay with Windows or NetworkManager.
Android doesn't let apps switch the hotspot on, so **Hotspot settings** in the
phone app opens the right Android page.

**Phone remote** turns your phone into a remote for apps on a computer. Turn it
on in Settings → Devices → Phone remote on the computer, choose which phones may
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
Offer new screenshots and photos in Settings → Connections.

**Pictures in messages (MMS):** conversations show Show picture for MMS parts.
The picture is fetched from the phone only then, kept in Saiph's own folder,
shown in the conversation, and saved to Downloads → Orion on request.

**Group conversations:** with an up-to-date Saiph on the phone, you can reply to
group conversations from the computer; replies are sent as MMS.

**Phone apps in their own windows:** the Apps tab lists the phone's apps and opens
one in its own window through scrcpy; Pin adds it to the Start menu or the
applications menu. It needs authorised wireless or USB debugging (as the phone
preview does) and Android 10 or later.

**Phone as a webcam (optional):** the phone camera appears as a webcam in video
calls through upstream scrcpy, with OBS Studio's Virtual Camera on Windows or a
v4l2loopback device on Linux. The video goes directly from the phone to the
computer over USB or wireless debugging on the local network, so it works with
Saiph Hosted and needs no Hub, Saiph pairing or Tailscale. It needs Android 12
or later and scrcpy 2.2 or later (scrcpy includes adb); installers do not bundle
scrcpy, adb, OBS or v4l2loopback. Turn it on in Settings → Devices → Phone camera
and follow **One-time camera setup**: Developer options and USB or Wireless
debugging on the phone, then the OBS scene (Windows, using **Open camera
preview** to create the window capture) or the loopback device (Linux). For
Wi-Fi, **Connect over Wi-Fi** accepts the phone's pairing address and six-digit
code once, then the address shown on the Wireless debugging screen each time it
changes; only private or link-local network addresses are accepted. Without a
self-hosted paired phone, **Find my phone** on the Phone page lists phones that
have allowed this computer and **Use phone as webcam** starts the chosen one.
Physical-device acceptance is pending.

**Pause Saiph on the phone:** add the Saiph widget to your home screen to see
whether Saiph is on and connected, and to pause or resume it with one tap.
Settings in the phone app has the same switch. While paused, nothing syncs and
Saiph does not restart, even after a reboot; pairing and settings are kept.

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

**Lock when my phone leaves (Linux):** in Settings → Devices, choose your
Bluetooth-paired phone; the session locks once it has been gone for the chosen
time. It never unlocks. On Windows, use Dynamic Lock in sign-in options instead.

Smaller conveniences, each with a switch in Settings → Connections:

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

## Desktop photos and preferences

Click a recent photo to open the window-filling viewer. It keeps the preview
visible while the original downloads, fits the image without changing its aspect
ratio, and offers actual-size zoom, arrow-key browsing, details, copy and save.
Escape closes the viewer. Right-click a tile or use its three-dot button for the
same original-image actions. Copy uses the original image with its orientation
applied; Save keeps the original file in Downloads → Orion. Hovering the grid
does not download originals.

The desktop header and bottom bar stay fixed while content scrolls inside the
window. Settings uses sidebar sections: **General** (this computer, startup and
the optional setup guide and a Phone connection shortcut), **Connections** (Cloud, clipboard and continuity, Saiph account,
your Hub and phone hotspot), **Devices** (phone camera and microphone, phone
remote and lock when your phone leaves), **Updates** and **Advanced**
(keyboard and mouse sharing).

While Saiph is open, returning to a page restores its scroll position and Phone
remembers the selected feature. SMS drafts stay with their conversation when you
switch conversations or tabs. Settings forms keep unfinished edits across
sections and show **Unsaved changes** until you choose Save; startup switches
apply immediately. These drafts are held in memory for the current session.

Cloud settings and phone camera/microphone setup buttons open the relevant
settings section directly. Cloud preferences include **Browse Cloud folder**,
timezone suggestions and a time picker for the end of quiet hours. Device setup
shows instructions for the current operating system.

A disconnected phone shows saved content and explains which actions need a
connection. Originals already cached on the computer can still be viewed, copied
and saved offline. Failed conversation or original-photo loads offer a Retry
action without discarding your draft or closing the viewer.
