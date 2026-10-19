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
   your other devices. If you already have a main computer, choose **Join as
   another computer** instead: compare the main computer's security code (shown in
   its Settings → Saiph Cloud), then approve this computer in the pop-up on the
   main computer. Deny or Block refuses a device you don't recognise. Pasting the
   main computer's code remains available.
3. Open Saiph on your phone and sign in with the same account. On the same Wi-Fi,
   tap **Find my computer**: both screens show the same six-digit code. Tap
   **Codes match** on the phone, then **Codes match, approve** on the computer
   (Windows asks you to confirm it's you). If the codes differ, stop and use the QR.
   Otherwise scan the QR shown in the desktop's Phone tab and compare every group
   of the computer's security code when the phone asks. The desktop moves on to
   approval by itself once the phone has scanned; **Continue to approval** is
   there if it does not.
4. With the QR: the phone's request appears on the approval screen. Choose **Review and approve**,
   compare every group of its security code with the phone, give it a name and
   approve it. **Back to scanning** returns to the QR if needed and clears any
   previous comparison. The desktop then waits for the phone to connect, tells
   you when it has, and **Done** opens the normal Phone page.

The security codes are fingerprints of the devices' encryption keys. Sign-in
finds your account; the comparisons check which devices you are trusting.
**Can't scan? Copy a code instead** and **My device hasn't appeared** contain
manual fallbacks. They still require the full security-code checks.

Add another phone from **Phone → Add a device**. Until a phone is connected,
Settings → General also has a **Connect a phone** shortcut to this flow. The
**Optional setup guide** in that section covers feature choices, optional tools
and privacy preferences; on a connected computer it starts at the feature
choices, and it does not interrupt first connection. Its **Set up later** action
closes it.

Choose **Use my own Hub instead** only if you manage your own server. Use its
private invitation to connect this computer, then scan its phone pairing QR.

## Android first connection

On first use, review the linked privacy policy and Cloud terms, then choose **Agree and continue**. Usage sharing and Android permissions remain separate choices. The phone then opens one illustrated welcome screen. **Subscribe** opens Saiph's
plans on the website. If you already have an account, **Continue with Google**
opens Google sign-in directly for the bundled Auth0 service. Existing email or
other-provider accounts can use **Other sign-in options** to keep their original
account; using the same email with a different provider need not select the same
Saiph account.

After sign-in, open **Phone → Add a device** on your computer and tap
**Find my computer** (same Wi-Fi, six-digit comparison) or **Scan QR code** on the phone. **Paste a code instead** remains available.
Compare the complete security codes when asked, then approve the phone on the
computer. Setup advances when approval arrives.

**Self-host instead** opens Hub pairing. Its header Back arrow, Android Back
gesture and **Back to Saiph** action return to the welcome screen. Leaving an
unfinished Hub invitation cancels its pending setup; wait for an active pairing
to finish before switching routes. After account sign-in, Back exits setup or returns from Settings to the current task; it does not return to the welcome menu. Approved phones open daily use. Account, subscription and connection controls live in Settings.

### Updating the Android app

Open **Settings → About & help → Version and updates → Check for updates**.
Saiph checks the place this phone already uses (your Saiph account, or your Hub
when self-hosting) and shows **Update available** with what's new. The
download button shows the size; on mobile data Saiph asks before downloading.
You can pause, leave the screen and resume later. Saiph checks that the download
is the published build, signed like the app you have, then Android asks you to
confirm the install. The first time, Android also asks you to allow Saiph to
install apps; the Update screen explains the step and opens that setting. Saiph
never installs an update without that confirmation, never installs an older
version, and deletes any download that fails a check. **Check automatically**
sends a notification when a new version is published; it does not download.

Saiph account phones need a service update before this works; until then the
screen says so and links to the downloads page. Tester builds installed through
Firebase App Tester can still update there from the same screen.

If setup is interrupted, Saiph shows **Finish connecting this phone**. Retry the existing identity, or explicitly remove its local setup and sign in to scan again. Existing protected keys and trust history are kept; remove any corresponding approval on your main computer too. A saved device ID alone never completes setup.

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
app and sends it to a paired computer, where it is saved in Downloads → Saiph
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
(Saiph) action. Saiph names the files, asks which phone and confirms before
sending; at most 20 files, each up to 2 GB with a self-hosted Hub. The tray's
Phone menu also has Send a file to phone.

**Files with Saiph Cloud:** when both devices are on the same Wi-Fi or private
network, a file of any size goes directly between them: Saiph Cloud only carries
an encrypted one-time invitation, and the file travels over an encrypted local
connection that only that device can open. The Share tab and Settings show
"Connecting to … on your network", then progress. The receiving device fetches
the file by itself, checks its exact size and fingerprint (SHA-256), and keeps it
privately until you save it (30 minutes on a computer); a damaged copy is
deleted. A short Wi-Fi drop (up to 90 seconds) resumes where it stopped; a longer
one fails on both sides with Retry. If the other device can't connect or doesn't
answer within about 30 seconds, a file up to 19.9 MB (20 967 424 bytes) goes
through Saiph Cloud instead. A larger file then fails with a message that both
devices must be on the same Wi-Fi or network with Saiph open, and a computer with
no private network refuses it before sending anything. Through Saiph Cloud, each
send is shown as waiting, sending with progress,
retrying after a lost connection, or sent to the device by name. If the
connection drops, Saiph resumes the same encrypted upload automatically, so the
recipient still gets one offer; after ten minutes without Saiph Cloud the send
fails with Retry. A received offer stays available for five minutes (the
service's limit) and the list says how long is left; offers still waiting are
shown again after Saiph restarts. On Android 10 and later, Save to Downloads
saves a received file to Downloads → Saiph in one tap; Save as… lets you choose.
Received files and saved photos all go to Downloads → Saiph, using the Downloads
folder Windows or your Linux desktop (`XDG_DOWNLOAD_DIR`) is set to. Clipboard
text over 16 KB is not shared; Saiph says so and suggests sending a file.

**New screenshots and photos:** when you take a screenshot or photo on the phone,
the computer shows a notice with Copy (it lands on the clipboard) and Save (to
Downloads → Saiph). Nothing transfers until you choose one. Turn it off with
Offer new screenshots and photos in Settings → Connections.

**Pictures in messages (MMS):** conversations show Show picture for MMS parts.
The picture is fetched from the phone only then, kept in Saiph's own folder,
shown in the conversation, and saved to Downloads → Saiph on request.

**Group conversations:** with an up-to-date Saiph on the phone, you can reply to
group conversations from the computer; replies are sent as MMS.

**Phone screen and apps:** **Mirror screen** at the top of the Phone page (or Phone →
Apps → **Show phone screen**) sends a request to your phone (Saiph Cloud) or shows a
code to scan in Phone → Apps. Nothing needs to be installed. On the phone, tap **Allow** in
the pop-up (when Saiph is open) or the notification, confirm it's you and choose
**Start now**. The phone's screen opens in its own window on the computer, sized
like the phone; move and resize it, use Back, Home, Recents and Rotate in its
toolbar, and close it or press **Stop** to end sharing. A red **Live** badge (and
a red dot on the tray icon) shows while the screen or camera is live. Below, the
phone's apps appear as icons with **Pinned** and **Most used** rows and a search
box; click one to open it on the phone. Right-click a tile (or use its "…") to
pin it or add it to the Start menu or applications menu. Icons need Saiph Cloud;
otherwise each app shows its initial. Most used counts only what you opened on
this computer. People who already use Android debugging can turn on Settings →
Advanced → **USB debugging** to also open apps in separate scrcpy windows.

**Phone as a webcam (optional):** Windows Saiph includes the webcam component.
Keep both devices on the same Wi-Fi, then choose **Phone → Webcam → Use phone as
webcam** on the computer. A phone connected with Saiph Cloud gets a notification,
**Start camera for <computer>?**; tap it. Otherwise, on Android choose **Use phone
as webcam → Scan computer's camera code**. Choose your front or rear camera and tap
**Start camera**. Verify the phone's owner and allow Android camera access. Select
**Saiph Camera** in your meeting app. No separate camera app or debugging setup
is needed for this path. Video travels directly through a pinned encrypted local
session; audio is off and video is not recorded. Leaving the phone camera screen,
locking the phone, disconnecting or choosing Stop ends sharing. Each session
lasts at most 30 minutes. **Preview camera** works without a virtual webcam.
The current implementation is limited to private IPv4 Wi-Fi/LAN, bounded 720p
frames and up to 15 fps; physical-phone and meeting-app acceptance remain pending.
Legacy scrcpy/OBS or Linux loopback settings are retained under Settings → Devices
→ **Legacy USB camera tools (advanced)**. See [camera details](PHONE_CAMERA.md).

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

Smaller conveniences, each with a switch in Settings → Connections. Like
Settings → Phone, Connections shows its sections open: **Phone and this
computer** (clipboard, verification codes, new photos, low battery, pausing
media during calls, finding this computer), **Quiet hours** (Do Not Disturb sync,
the shared sleep plan, its timezone and end time) and **Cloud folders**. A switch
saves as soon as you change it; the quiet-hours times and the Cloud folder path
save with their own button.

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

Saiph looks for a desktop update by itself shortly after it starts and every six
hours. When one is available, a glowing **Update to x.y.z** button appears at the
bottom right of the window, beside the version. Click it and Saiph checks again,
downloads and verifies the update, then closes, installs it and reopens. If
anything fails, the button says **Update failed · Try again** and your installed
version keeps running.

You can also open **Settings → Updates → Check for updates**.
Updates come from your Saiph account, or from your Hub when self-hosting. When
a newer version exists, Saiph shows what's new and **Download update** with its
size. The download shows its progress and is checked against the published
build; nothing changes until you choose **Restart to update**, which closes
Saiph, installs the new version and reopens it. If anything fails, your
installed version stays and reopens. Older versions are never installed. Saiph
account computers need a service update before this works; until then the
panel says so and you can download the latest version from your account.

## Troubleshooting and privacy

Check that the private network is connected, the Hub is reachable, the devices
are still admitted and Android permissions/background settings allow the feature.
Restart affected components before changing keys or pairing identities. Do not
delete an existing data directory as a generic repair step.

The existing self-hosted Hub can process readable content. Network encryption and
device signatures do not make every feature end-to-end encrypted. See the
[security model](SECURITY_MODEL.md) before choosing where to run it.

The desktop's **Settings → Help** has the same quick fixes:

- **General:** Saiph on the phone says Connected; with Saiph Cloud both devices
  use the same account. Let Saiph run in the background (Android Settings → Apps
  → Saiph → Battery → Unrestricted). With Sync over mobile data off, the phone
  pauses until it is on Wi-Fi. Refresh next to the phone's name asks it for its
  latest status.
- **Apps:** apps open on the phone and show in the phone screen window over your
  Wi-Fi. Apps that block screen capture (banking, passwords) show black.
- **Calls:** turn on Texts and calls in Saiph on the phone and allow its phone
  permissions; turn on Calls in Settings → Phone. Call audio stays on the phone.
- **Messages:** Texts and calls on the phone, with SMS access. With Saiph Cloud,
  group replies stay in the phone's messaging app.
- **Notifications:** tap Allow notifications in Saiph on the phone; music
  controls use the same access. Turn on Notifications in Settings → Phone.
  Each notification shows as a card with the app, title, the first lines of the
  text (**Show more** for the rest) and how long ago it arrived. Several from one
  app are grouped under that app with a **Clear** for the group. Phones don't send
  app icons yet, so each app gets a coloured tile with its initials. The newest
  Saiph Cloud notification also appears in Settings → Connections → Saiph Cloud.
- **Phone screen:** mirroring uses scrcpy (install it once in Settings →
  Advanced) and wireless or USB debugging; keep the phone unlocked the first time.

- **Phone screen:** keep both devices on the same Wi-Fi or private network; on the
  phone tap Allow, confirm it's you and choose Start now. No cable or install.
- **Photos:** allow the photo gallery in Saiph on the phone and choose which
  photos Android shares; only recent photos are shown.

Send feedback in Settings → Help opens a new issue on the public repository.
Report ordinary bugs with the version, OS/phone model, reproducible synthetic
steps and sanitized metadata. Follow [SECURITY.md](../SECURITY.md) for private
vulnerability reports. Never attach messages, tokens, keys or personal databases.

## Desktop photos and preferences

Click a recent photo to open the window-filling viewer. It keeps the preview
visible while the original downloads, fits the image without changing its aspect
ratio, and offers actual-size zoom, arrow-key browsing, details, copy and save.
Escape closes the viewer. Right-click a tile or use its three-dot button for the
same original-image actions. Copy uses the original image with its orientation
applied; Save keeps the original file in Downloads → Saiph. Hovering the grid
does not download originals.

The desktop header and bottom bar stay fixed while content scrolls inside the
window. Settings uses sidebar sections: **General** (this computer, startup and
the optional setup guide and a Phone connection shortcut), **Connections** (Saiph account,
phone and this computer, quiet hours, Cloud folders, phone hotspot and, folded away
until you use one, a self-hosted Hub), **Devices** (phone camera and microphone, phone
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

## Phone photos and messages with Saiph Cloud

After approving the phone, a three-step sharing setup offers photos, notifications, and texts/calls. Each is optional. Tap **Allow photo gallery** and grant Android access to all photos or selected photos. You can also do this from **Files and photos** on the phone's daily screen. **Manage photo access** reopens Android's selection or app settings. If Android has stopped showing permission prompts after a denial, Saiph opens app settings instead. The desktop **Phone → Photos** gallery shows up to 100 recent accessible photos, with bounded previews up to 384 pixels across. Open, copy or save an original on demand; transfers are limited to 19.9 MB. Stop sharing photos on the phone to stop new gallery transfers. Files explicitly saved on a computer remain there.

For SMS conversations, tap **Allow texts and calls** on the phone and grant Android's SMS/phone permissions. Open **Phone → Messages** on the desktop. Tap **Allow notifications** on the phone to open Android's notification access settings. Notifications then appear on the desktop's **Phone** page for the selected phone. New and changed ones also pop up as desktop notifications (a Windows notification, or a desktop popup on Linux) on your main computer and on every joined computer. Click one to open Saiph on the Phone page. Dismissing it on the computer, or in Saiph, dismisses it on the phone too, and one removed on the phone disappears from the computer. Repeated updates with the same text do not pop up again, and notifications that were already showing on the phone (for example when it reconnects) are listed without popping up. Quiet hours and the Notifications switch in Settings → Phone silence the popups; with automatic code copying on, a new one-time code is still copied. Other apps' messages appear as notifications; this does not sync their full chat histories. Android restrictions, offline devices and device approval still apply.

The packaged Cloud app requests a rotating refresh token and stores it encrypted with Android Keystore so sign-in survives closing the app and access-token expiry. Existing installs need one new sign-in to obtain this session. A network failure retries without deleting the saved session; explicit sign-out or an invalidated refresh token requires sign-in again. Custom service builds retain their refresh-token choice. The identity provider must enable offline access and rotating refresh tokens for the native client before distributing this APK.

The desktop's bottom-right corner shows the installed package version. Source checkouts show a development version.
