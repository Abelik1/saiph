# Saiph self-hosting beta guide

**Most testers do not need this guide.** With a Saiph account, Saiph runs the
connection for you: follow the setup page on the account website and choose
**Saiph account** when the apps ask. You install nothing else: no server and no
Tailscale on your phone or computer. Use this guide only if you chose
**I self-host my own Hub** and want to run your own server.

This guide walks you through self-hosting Saiph from scratch, step by step. It
assumes you can follow instructions carefully but have rarely used a terminal.
Every command is shown in full; copy it exactly.

Saiph is beta software. Things will go wrong, and finding them is the point of the
beta. Use test data (harmless text, test files) until the basics work.

Items marked **TO CONFIRM** have not been checked against a real beta release yet.
If what you see differs, follow what you see and tell Alexander.

## Contents

1. [What you need](#1-what-you-need)
2. [Create the server and install the Hub](#2-create-the-server-and-install-the-hub)
3. [Tailscale on your computer and phone](#3-tailscale-on-your-computer-and-phone)
4. [Install the desktop app](#4-install-the-desktop-app)
5. [Install the Android app](#5-install-the-android-app)
6. [Pair your computer and phone](#6-pair-your-computer-and-phone)
7. [Android permissions and first checks](#7-android-permissions-and-first-checks)
8. [Stuck? Check this first](#8-stuck-check-this-first)
9. [Sending a useful bug report](#9-sending-a-useful-bug-report)
10. [Leaving the beta](#10-leaving-the-beta)

## How the pieces fit

Saiph has three parts:

- **The Hub**: a small service on a Linux server you control. Your devices talk to
  each other through it.
- **Saiph Link**: the desktop app for Windows or Linux.
- **The Saiph Android app** on your phone.

When you self-host, all three join a private network made with **Tailscale**, a
free service that links your own devices securely. Saiph accounts do not use it.
The Hub listens only on that private network, never on
the open internet.

Some internal names still say **Orion** (Saiph's old codename): file names such as
`.orion-enrollment`, the `orion-server` command and some folders. That is expected.

**What the Hub can see.** Your Hub handles notifications, messages and clipboard
text in readable form. Tailscale encrypts traffic between devices, but this is not
end-to-end encryption: whoever controls the server (you, and in principle your
cloud provider) could read that data. See the [security model](SECURITY_MODEL.md).

## 1. What you need

- **An Android phone**, Android 8.0 or newer. Behaviour varies by manufacturer and
  Android version.
- **A Windows 10/11 or Linux computer** (64-bit x86). On Linux, Ubuntu is the
  tested desktop.
- **A small Ubuntu 24.04 server.** A basic cloud virtual machine (VM) is enough:
  1 GB memory and a few GB of disk, typically about $6 a month from providers such
  as DigitalOcean, Hetzner, Linode or Vultr. The installer needs at least 512 MB of
  free memory and 1 GB of free disk. A Raspberry Pi 4/5 or other home Linux machine
  also works, but this guide assumes a cloud VM.
- **A free Tailscale account** ([sign up](https://tailscale.com/)). You can sign in
  with an existing Google, Microsoft, GitHub or Apple account.
- **The Saiph beta files from Alexander**: the server package and the desktop
  installer, plus a Firebase App Distribution email invitation for the Android app
  (section 5). **TO CONFIRM:** how and where the server package and desktop
  installer are shared (a private release page or a direct link).

**Time:** plan for 1 to 2 hours the first time, mostly creating the server and
waiting for installs. Setting up another device later takes about 15 minutes.

## 2. Create the server and install the Hub

### 2.1 Create the VM

1. In your cloud provider's dashboard, create a new server (it may be called a
   "Droplet", "instance", "VM" or "Linode").
2. Choose **Ubuntu 24.04 LTS** as the image, the smallest plan with at least 1 GB
   of memory, and any region near you.
3. For login, choose **SSH key** if you know how. Otherwise choose a strong
   password and save it in your password manager.
4. Do **not** open any extra firewall ports. Saiph needs none; Tailscale connects
   outward on its own.
5. Create the server and note its **public IP address**. Below, replace
   `SERVER_ADDRESS` with that address.

![Cloud provider page with Ubuntu 24.04 selected](images/beta-guide/vm-create-ubuntu.png)

Some providers log you in as `root`; others give you a user such as `ubuntu`.
The examples below use `root`. If your provider gave you another user name, use
that instead.

### 2.2 Copy the server package to the server

On your computer, open a terminal:

- **Windows:** press Start, type **PowerShell**, press Enter.
- **Linux:** open your **Terminal** app.

Go to the folder containing the server package (usually Downloads), then copy it:

```sh
cd Downloads
scp saiph-server.tar.gz root@SERVER_ADDRESS:
```

- `cd Downloads` moves the terminal into your Downloads folder.
- `scp` copies a file to another computer over SSH. The `:` at the end means
  "into my home folder on the server".

The first time, it asks *"Are you sure you want to continue connecting?"* Type
`yes` and press Enter, then enter the server password if asked (typing shows
nothing; that is normal).

**TO CONFIRM:** the exact package file name. It may include a version number; use
the real name in every command.

### 2.3 Log in to the server

```sh
ssh root@SERVER_ADDRESS
```

`ssh` opens a terminal on the server. The prompt changes to something like
`root@your-server:~#`. Every command until section 2.6 runs **on the server**.

Optional: if Alexander published a checksum for the package, check it:

```sh
sha256sum saiph-server.tar.gz
```

This prints a long code. It must match the published one exactly. If it doesn't,
stop and tell Alexander. **TO CONFIRM:** where checksums are published.

### 2.4 Run the installer

These are the two commands from the [self-hosted server guide](ORION_SELF_HOSTED_SERVER.md):

```sh
tar -xzf saiph-server.tar.gz
sudo python3 orion-server/install.py
```

Line by line:

- `tar -xzf saiph-server.tar.gz` unpacks the package into a new folder called
  `orion-server`.
- `sudo python3 orion-server/install.py` runs the installer with administrator
  rights (`sudo`). Ubuntu 24.04 already includes `python3`.

The installer then:

1. Checks the system: Ubuntu 22.04/24.04 or Debian 12/13, enough memory and disk.
2. Installs a few system packages.
3. Installs the official Tailscale client if it isn't there yet, and asks you to
   sign in (next step).
4. Creates a dedicated `orion-server` service account and installs the Hub as a
   background service that starts automatically.
5. Checks the Hub is healthy and creates your **first invitation**.

It opens no public ports and creates no public web address.

### 2.5 Sign the server in to Tailscale

During installation you will see:

> Complete the official Tailscale sign-in in your browser. Saiph adds no account or password.

followed by a link starting with `https://login.tailscale.com/`. Copy the link
into a browser on your computer, sign in to **your** Tailscale account and approve
the server.

You have about **two minutes**. If the installer stops with *"A required
installation step failed; existing data was preserved"*, just run
`sudo python3 orion-server/install.py` again. If you already signed the server in
to Tailscale yourself, the installer uses that and skips this step.

![Installer waiting for Tailscale sign-in (link hidden)](images/beta-guide/server-installer-tailscale-login.png)

Tip: Tailscale signs devices out after a while by default. For the server, you can
turn this off in the Tailscale admin console; see Tailscale's
[key expiry](https://tailscale.com/kb/1028/key-expiry) page.

### 2.6 Note the invitation location

When the installer finishes, it prints something like:

```text
Private first-device invitation and QR: /root/.../device-1234567890.orion-enrollment
Saiph server is healthy. Create a separate private invitation for each device:
  sudo orion-server enroll --output /var/lib/orion-server/device.orion-enrollment
```

Copy the full path after *"Private first-device invitation and QR:"* somewhere
temporary. (If you logged in as a normal user rather than root, it is in your
home folder under `.local/share/OrionServerInvites/`.)

This invitation is for your **computer**. It works **once** and **expires after
30 minutes**, so continue straight on to sections 3, 4 and 6. If it expires,
section 6.4 shows how to make a new one.

![Installer finished, showing the invitation path](images/beta-guide/server-installer-finished.png)

**Invitations are private.** Anyone holding one before it expires could add a
device to your Hub. Never paste it, or a photo of its QR code, into chat, email, a
bug report or an issue.

Type `exit` to leave the server and return to your own computer's terminal.

## 3. Tailscale on your computer and phone

All three devices must be signed in to the **same** Tailscale account.

- **Computer:** install Tailscale from the official
  [download page](https://tailscale.com/download) and sign in. Alternatively,
  Saiph offers **Install connection component** and **Continue browser sign-in**
  buttons during pairing (section 6), which install and sign in the same
  official Tailscale.
- **Phone:** install Tailscale from Google Play
  ([Android instructions](https://tailscale.com/kb/1079/install-android)), sign in,
  and accept Android's VPN prompt. The Saiph app also has an **Install Tailscale**
  button.

Check: open the [Tailscale admin console](https://login.tailscale.com/admin/machines).
Your server, computer and phone should all be listed as connected.

![Tailscale admin console listing three devices (names hidden)](images/beta-guide/tailscale-admin-machines.png)

On the phone, avoid using a Tailscale **exit node** with Saiph.

## 4. Install the desktop app

### Windows

1. Download the Windows installer from the link Alexander shared. It is named like
   `Saiph-Link-0.1.0-beta.1-windows-x86_64.exe` (version may differ).
2. Your browser may warn that the file is not commonly downloaded. Choose to keep it.
3. Double-click the installer. Windows will probably show a blue
   **"Windows protected your PC"** (SmartScreen) window.
4. Click **More info**, check the app name, then click **Run anyway**.

   This warning appears because beta builds are **not yet code-signed**: Windows
   cannot confirm who published the file. Publisher signing is a release task that
   is not finished yet. Only do this for the file Alexander sent you; if anything
   about it seems wrong, stop and ask.

5. In the **Install Saiph** window, click **Install Saiph**. It installs for your
   Windows user only. Saiph opens when finished; later, open it from the Start
   menu.

![SmartScreen with "More info" link](images/beta-guide/windows-smartscreen-more-info.png)
![SmartScreen with "Run anyway" button](images/beta-guide/windows-smartscreen-run-anyway.png)
![Install Saiph window](images/beta-guide/windows-installer.png)

### Linux

The easiest route is the setup file, named like
`Saiph-Link-0.1.0-beta.1-linux-x86_64.run`. This setup file is new and has not yet
been tested on real GNOME, KDE and Xfce desktops. If any step below doesn't
match what you see, use the archive route further down and tell Alexander.

1. Download the `.run` file from the link Alexander shared.
2. Allow it to run as a program. In your file manager, right-click the file and
   choose **Properties → Permissions**, then turn on the option to allow
   executing it as a program. Some desktops instead offer **Run as a Program**
   directly in the right-click menu. The wording varies by desktop.
3. Double-click the file. A window asks *"Install Saiph ... for your user
   account?"* Click **Install**. Saiph installs in your home folder, so no
   administrator password is needed.
4. When it finishes, click **Open Saiph**, or **Close** and open Saiph later from
   your applications menu.

If no window appears, the file may open in a terminal window instead and print
its progress there. If installation fails, the error window names a log file
(`~/.cache/saiph-setup.log`). Read it before sending any of it to Alexander.

![File Properties with "allow executing as program" turned on](images/beta-guide/linux-run-permissions.png)
![Saiph setup asking to install](images/beta-guide/linux-setup-install.png)
![Saiph setup finished with "Open Saiph"](images/beta-guide/linux-setup-done.png)

**Fallback: the archive.** If the `.run` file doesn't work, download the archive,
named like `Saiph-Link-0.1.0-beta.1-linux-x86_64.tar.gz`. Open a terminal in the
download folder and run these commands as your normal user (**not** with `sudo`):

```sh
tar -xzf Saiph-Link-0.1.0-beta.1-linux-x86_64.tar.gz
./orion/install.sh
```

- The first line unpacks the archive into a folder called `orion`.
- The second installs Saiph for your user only, adds a menu entry and lets
  `.orion-enrollment` files open in Saiph.

It finishes with *"Saiph installed. Open it from your application menu"*.

Both routes install the same thing. If either reports that the package needs a
newer glibc, your Linux is too old for this build; tell Alexander. Close Saiph
before installing a newer version.

![Linux archive install finished in the terminal](images/beta-guide/linux-install-terminal.png)

## 5. Install the Android app

Android beta builds are shared through **Firebase App Distribution**, a Google
service for sending test apps. Outside testers receive the **beta** build type,
which is **not debuggable**. It still includes Firebase App Distribution for
beta update checks.

1. You receive an email from Firebase App Distribution inviting you to test
   Saiph. If Alexander gave you an invite link instead, open it and enter your
   email address first.
2. Open the email **on your Android phone**, sign in with a Google account and
   accept the invitation.
3. You can install Firebase's optional **App Tester** app when your browser
   offers it, or download the Saiph app file (APK) directly in the browser.
4. Android asks you to allow **Install unknown apps** for App Tester or your
   browser. Allow it for that app only, then confirm the installation.
5. Google Play Protect may warn about an unrecognised app. **TO CONFIRM:** the
   exact wording. If it offers *Install anyway*, that is expected for beta builds.
6. After installing, you can turn **Install unknown apps** off again in Android
   Settings.

![Firebase App Distribution invitation email](images/beta-guide/android-firebase-invite.png)
![Firebase App Tester showing the Saiph release](images/beta-guide/android-app-tester.png)
![Android "Install unknown apps" setting](images/beta-guide/android-install-unknown-apps.png)

**Updates.** New beta releases arrive by email. After pairing, Saiph's
**Settings → Check for updates** first asks your Hub, then Firebase. The first
time, it asks you to sign in with Google. Declining doesn't affect pairing. On
Android 13 and newer, allow Saiph's notifications to see download progress. Each
update still needs you to confirm Android's install prompt, and Saiph asks once
for its own **Install unknown apps** permission.

**What Firebase and Google receive.** Firebase App Distribution processes tester
names and email addresses. Its documented data categories also include Firebase
installation IDs and secure Android IDs. Whether App Distribution creates a
Firebase installation ID in this push-disabled beta remains **UNVERIFIED**; the
provider's list of supported data categories does not establish what this build
sends at runtime.

**Push is off by default.** Outside tester builds disable Google's messaging
service (FCM): Saiph does not fetch or upload an FCM registration token. App
Distribution update checks remain enabled. Your messages, notifications,
clipboard, files and contacts go only to **your own** Hub, not to Firebase.
Saiph includes no Firebase Analytics or Crashlytics. Builds that include the
Saiph service ask once whether to share anonymous daily usage counts; it stays
off unless you agree, and Settings shows exactly what is sent (see
[usage statistics](USAGE_ANALYTICS.md)).

Keep your phone locked, and leave USB or wireless debugging off unless you need
it (see **Background clipboard** in section 7).

Removing you from the beta does not uninstall the app or unpair your phone.

**Never uninstall Saiph to fix a problem or to update.** Uninstalling deletes the
phone's private key and pairing. Updates must come from the same publisher so they
install over the top.

## 6. Pair your computer and phone

Pairing uses the invitations from your Hub. Each device needs its own invitation.

### 6.1 Copy the computer invitation from the server

On your computer's terminal (not the server), using the path you noted in 2.6:

```sh
scp root@SERVER_ADDRESS:/the/path/you/noted/device-1234567890.orion-enrollment .
```

The final ` .` means "into the folder I'm in now". On Windows that is usually
your user folder (`C:\Users\YourName`) unless you changed folders with `cd`.

### 6.2 Open it in Saiph

1. Double-click the `.orion-enrollment` file. Or, in Saiph's setup guide (it opens
   on first run, or from **Settings → General → Setup guide**), choose
   **I self-host my own Hub**, click **Continue**, then **Open server invitation**
   and choose the file. Saiph preselects **Saiph account**; self-hosting is
   always your explicit choice.
2. Saiph shows *"Your invitation is ready. Approve it to pair this computer."*
   Click **Use invitation** only if this is your own server's invitation.
3. If Tailscale isn't running on this computer yet, click
   **Install connection component** and then **Continue browser sign-in**, and
   approve any Windows or Linux prompts.
4. Saiph shows *"Waiting for your server. Pairing continues automatically while
   your invitation is valid."* Wait.
5. To confirm, open **Settings** in Saiph. The **Saiph Hub** card should say
   *"This computer is paired."*

![Welcome to Saiph card with "Open server invitation"](images/beta-guide/desktop-welcome.png)
![Invitation ready with "Use invitation"](images/beta-guide/desktop-use-invitation.png)
![Settings showing "This computer is paired."](images/beta-guide/desktop-paired.png)

Then delete the invitation file from your computer. It cannot be used again.

### 6.3 Pair the phone

Make sure Tailscale on the phone is signed in to the same account **before** you
start: the phone retries pairing for only about 10 minutes after scanning.

**Option A: scan a QR code from your paired computer (easiest).**

1. On the computer, open Saiph's **Phone** page. Under **Add a device** beneath
   the phone name (or **Your phone**), click **Show pairing QR**.
2. On the phone, open Saiph and tap **I self-host my own Hub** (the app starts
   on Saiph account sign-in). Under **Pair with your own Hub**, tap
   **Scan pairing QR** and scan the code on your computer screen.
3. Tap **Use invitation** in the *"Use this Saiph invitation?"* dialog.
4. Saiph shows *"Your invitation is ready"* and waits for Tailscale. When pairing
   succeeds it moves on to **Make Saiph automatic** (section 7).

The desktop QR works **once** and expires after **10 minutes**. Its countdown
shows the time left. It disappears when a new device is admitted or the timer
expires. **Close** hides the QR but does not revoke the invitation before expiry.
It is a private credential: show it only to your own phone. Do not photograph,
share or screen-share it.

![Desktop Phone page with Show pairing QR and countdown (QR fully hidden)](images/beta-guide/desktop-pairing-qr.png)

**Option B: save an invitation file from your paired computer.**

1. On the computer's **Phone** page, under **Add a device**, click
   **Save invitation file**. Save the `.orion-enrollment` file. It works once and
   expires after **10 minutes**.
2. Copy the file to the phone privately, for example by USB cable.
3. In the phone's Saiph app, tap **I self-host my own Hub**, then
   **Open invitation**, choose the file and tap **Use invitation**.
4. Delete your copies of the invitation file after pairing.

Don't send invitations through email, messaging apps or shared cloud folders.

**Fallback: scan a QR code from the server.**

Use this route if no paired computer is available or the desktop QR does not
work.

1. Log in to the server (`ssh root@SERVER_ADDRESS`) and run:

   ```sh
   sudo orion-server enroll --output /var/lib/orion-server/enrollments/phone.orion-enrollment --minutes 30
   sudo cp /var/lib/orion-server/enrollments/phone.svg ~/phone.svg
   sudo chown "$USER" ~/phone.svg
   exit
   ```

   - The first line creates a phone invitation valid for 30 minutes, plus a QR
     code image `phone.svg` next to it. It prints *"Private invitation and QR
     written"*.
   - The next two lines copy the QR image to your home folder so you can download
     it.
   - `exit` returns to your computer.

   Each output name works only once. For another phone, use a new name such as
   `phone2.orion-enrollment`.

2. On your computer, download and open the QR:

   ```sh
   scp root@SERVER_ADDRESS:phone.svg .
   ```

   Double-click `phone.svg`; it opens in your web browser.

3. On the phone, open Saiph. Under **Pair once**, tap **Scan pairing QR** and scan
   the code on your computer screen.
4. Tap **Use invitation** in the *"Use this Saiph invitation?"* dialog.
5. Saiph shows *"Your invitation is ready"* and waits for Tailscale. When pairing
   succeeds it moves on to **Make Saiph automatic** (section 7).
6. Delete `phone.svg` from your computer, and from the server with
   `ssh root@SERVER_ADDRESS rm phone.svg`.

![Android "Pair once" screen](images/beta-guide/android-pair-once.png)
![Android "Use this Saiph invitation?" dialog](images/beta-guide/android-use-invitation.png)

### 6.4 If an invitation expired or was used up

If your computer is already paired, go to **Phone → Add a device** and choose
**Show pairing QR** again (or **Save invitation file**). An expired QR disappears
automatically; use the new invitation rather than a saved image of the old one.

If the computer is not paired yet or you cannot use it, create a new invitation
on the server:

```sh
sudo orion-server enroll --output /var/lib/orion-server/enrollments/computer2.orion-enrollment --minutes 30
```

Then copy it with `sudo cp` and `sudo chown`, as in 6.3, and download it with
`scp`. `--minutes` accepts 1 to 60 (default 10).

To list devices paired with your Hub:

```sh
sudo orion-server devices
```

## 7. Android permissions and first checks

After pairing, the phone shows **Make Saiph automatic**. Each item has
**Set up** (or **Manage** once done). Optional items never block
**Finish setup**, and you can return later via **Settings → Setup permissions**.

### Everyday operation (recommended)

- **Saiph notifications:** lets Saiph show its own status notification.
- **Battery exemption:** stops Android from putting Saiph to sleep. Without it,
  Saiph may disconnect when the screen is off.
- **Automatic connection:** shows *"Ready · connected automatically"* when Saiph
  can reach your Hub.

Some manufacturers (Samsung, Xiaomi, OnePlus and others) have extra battery
settings that close background apps. Allow Saiph **and** Tailscale to run in the
background. [dontkillmyapp.com](https://dontkillmyapp.com/) has per-manufacturer
instructions.

In Saiph's **Settings → Advanced**, the **VPN settings** button opens Android's
VPN page. For Tailscale, turn **Always-on VPN** on and
**Block connections without VPN** off, and use no exit node.

### Optional features

Grant only what you want to test.

| Item in the app | Used for | Android grants |
| --- | --- | --- |
| Phone notification access | Showing phone notifications on your computer | Notification access (special setting) |
| Messages and calls | Texts and calls on your computer | SMS, phone, call log, contacts |
| Recent photos | Recent photos on your computer | Photos/media |
| Sleep plan quiet hours | Shared quiet hours | Do Not Disturb access |
| Background clipboard | Sending phone clipboard while Saiph is in the background | Developer options and USB/wireless debugging (advanced) |

On Android 13 and newer, sideloaded apps may hit a **"Restricted setting"**
message when you turn on notification access or SMS. To allow it: open Android
**Settings → Apps → Saiph**, tap the three-dot menu, choose
**Allow restricted settings**, then try again. The wording varies by phone.
**TO CONFIRM** with the beta build.

**Background clipboard** is advanced and optional. It needs Developer options and
USB or wireless debugging authorised for your computer, and may need re-enabling
after a phone reboot. Authorising debugging gives that computer powerful access
to your phone. Only authorise your own trusted computer, and skip this feature
unless Alexander asks you to test it. The outside beta app itself is not
debuggable (section 5).

![Make Saiph automatic screen](images/beta-guide/android-make-saiph-automatic.png)
![Android notification access list](images/beta-guide/android-notification-access.png)
![Allow restricted settings menu](images/beta-guide/android-restricted-settings.png)

### First checks

Use harmless test content only.

1. **Phone online:** on your computer, open Saiph's **Phone** page. Your phone's
   name should show **Online**, with its battery level.
2. **Notification:** with **Phone notification access** on, have a notification
   appear on your phone, for example by texting yourself "Saiph test 1" from
   another phone. It should appear in the computer's **Notifications** list.
   Dismissing it there (the **X**) should dismiss it on the phone.
3. **Clipboard, computer to phone:** copy the text `saiph clipboard test` on the
   computer, then paste it into any text field on the phone.
4. **Clipboard, phone to computer:** copy text on the phone with Saiph open, then
   paste on the computer. Android restricts background clipboard access, so this
   may only work with Saiph open or with **Background clipboard** set up.
   **TO CONFIRM** the expected behaviour without it.

Both apps have a **Share clipboard across my devices** setting (computer:
**Settings**; phone: **Settings → Focus**). It is on by default.

Write down what worked and what didn't. That is your first test report.

![Desktop Phone page with phone online and a test notification](images/beta-guide/desktop-phone-online.png)

## 8. Stuck? Check this first

Work through these in order. Restart things before changing anything else, and
never delete Saiph's data folders as a fix.

1. **Is Tailscale connected on all three devices, same account?** Check the
   [admin console](https://login.tailscale.com/admin/machines). This is the most
   common cause.
2. **Is the Hub running?** On the server:

   ```sh
   sudo systemctl status orion-server
   curl -s http://127.0.0.1:8765/v1/health
   ```

   The first should say `active (running)`; press `q` to exit. The second should
   print text containing `"ok":true`. If not, try
   `sudo systemctl restart orion-server` and check again.
3. **Is the device still paired?** Run `sudo orion-server devices` on the server.
4. **Did the invitation expire or get used?** Messages such as *"This invitation is
   invalid or expired"* mean you need a fresh one (section 6.4).
5. **Phone stuck on "Waiting for Tailscale…"?** Open Tailscale on the phone, make
   sure it is connected and has no exit node, then return to Saiph.
6. **Phone shows "This phone is already paired"?** It is still paired to a server.
   Don't uninstall to reset; ask Alexander first.
7. **No notifications on the computer?** Check **Phone notification access**,
   **Battery exemption** and your manufacturer's background settings, and that the
   phone shows **Online** on the computer.
8. **Everything was working and stopped?** Restart Saiph on the computer, reopen
   the phone app, then reboot the phone. Check Tailscale is still signed in on
   each device.

Common installer messages:

| Message | What to do |
| --- | --- |
| *Supported servers: Ubuntu 22.04/24.04 or Debian 12/13, amd64/arm64* | Recreate the VM with Ubuntu 24.04. |
| *At least 512 MiB available memory is required for installation* | Pick a plan with more memory. |
| *Complete the official mesh sign-in before installing Saiph* | Finish the Tailscale sign-in, then rerun the installer. |
| *A required installation step failed; existing data was preserved* | Rerun the installer; if it fails again, report it. |
| *Another Saiph server installation is running* | Wait for the other run to finish. |
| *The Hub port is in use* | Report it; don't change ports unless asked. |

To report a lost or stolen device, remove it from your Hub:
`sudo orion-server revoke DEVICE_ID` (find the ID with `sudo orion-server devices`).
Also remove it from the Tailscale admin console.

## 9. Sending a useful bug report

A good report lets someone else repeat the problem. Include:

- **Versions:**
  - **Android:** Saiph **Settings** shows *"Saiph x.y.z"*.
  - **Windows:** the installer file name.
  - **Linux:** run `cat ~/.local/lib/orion/current/VERSION`.
  - **Server:** run `ls /opt/orion-server/releases`.
- **Devices:** computer OS (e.g. Windows 11), phone model and Android version.
- **Steps:** what you did, step by step, using test content.
- **Expected vs actual:** what should have happened and what did.
- **Exact error text**, retyped, or a screenshot that shows no personal data.
- **When** it happened (date, time, time zone), and whether it happens every time.

**Never include:**

- Invitation files, their QR codes or pairing codes
- Tailscale keys or sign-in links
- Real messages, notification text, contact names or phone numbers
- Screenshots showing personal content
- Databases or files from `/var/lib/orion-server` or `/etc/orion-server`

If you copy server log lines (`sudo journalctl -u orion-server --since "30 min ago"`),
read them first and send only the relevant error lines, with anything personal
removed.

Where to send reports: if you have repository access, use the GitHub **Bug
report** form. Otherwise use the channel Alexander gave you. **TO CONFIRM:** the
tester feedback channel.

**Security problems** (for example, a way to pair without a valid invitation)
should not go in a normal report. Follow [SECURITY.md](../SECURITY.md) to report
privately.

## 10. Leaving the beta

- **Server:** delete the VM in your provider's dashboard to stop charges. This
  deletes everything on it.
- **Tailscale:** remove the server (and any devices you no longer want) in the
  admin console.
- **Windows:** uninstall **Saiph** from Settings → Apps. Uninstalling keeps your
  settings and keys on the computer. **TO CONFIRM:** how to remove that data too.
- **Linux:** run `~/.local/lib/orion/current/install.sh --uninstall`. This removes
  the menu entry and launcher but keeps installed files, keys and settings.
  **TO CONFIRM:** how to remove those too.
- **Android:** uninstall Saiph normally. This deletes its key and pairing.

## Screenshots needed

Placeholders above point to `docs/images/beta-guide/`. Capture each one using a
test profile and synthetic data. Hide public IPs, Tailscale names and addresses,
account emails, sign-in links, invitation paths that identify you, and all QR
codes.

| File | What to capture |
| --- | --- |
| `vm-create-ubuntu.png` | Provider's create-server page with Ubuntu 24.04 selected |
| `server-installer-tailscale-login.png` | Installer waiting for Tailscale sign-in, link hidden |
| `server-installer-finished.png` | Installer success output with the invitation line |
| `tailscale-admin-machines.png` | Tailscale admin console with server, computer and phone connected |
| `windows-smartscreen-more-info.png` | SmartScreen dialog showing **More info** |
| `windows-smartscreen-run-anyway.png` | SmartScreen dialog showing **Run anyway** |
| `windows-installer.png` | The **Install Saiph** window |
| `linux-run-permissions.png` | File Properties → Permissions with executing as a program allowed for the `.run` file |
| `linux-setup-install.png` | Saiph setup dialog asking to install, with **Install** button |
| `linux-setup-done.png` | Saiph setup finished dialog with **Open Saiph** |
| `linux-install-terminal.png` | Fallback: terminal after `./orion/install.sh` finishes |
| `android-firebase-invite.png` | Firebase App Distribution invitation email (tester address hidden) |
| `android-app-tester.png` | Firebase App Tester listing the Saiph release |
| `android-install-unknown-apps.png` | Android **Install unknown apps** toggle |
| `desktop-welcome.png` | **Welcome to Saiph** card with **Open server invitation** |
| `desktop-use-invitation.png` | Invitation ready with **Use invitation** |
| `desktop-paired.png` | Settings → **Saiph Hub** showing *This computer is paired.* |
| `desktop-pairing-qr.png` | **Phone → Add a device → Show pairing QR**, countdown and private-invitation warning; completely cover the QR modules |
| `android-pair-once.png` | Phone **Pair once** screen |
| `android-use-invitation.png` | *Use this Saiph invitation?* dialog |
| `android-make-saiph-automatic.png` | **Make Saiph automatic** checklist |
| `android-notification-access.png` | Android notification access list with Saiph |
| `android-restricted-settings.png` | App info menu with **Allow restricted settings** |
| `desktop-phone-online.png` | Desktop **Phone** page, phone **Online**, synthetic notification |
