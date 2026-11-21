// SPDX-License-Identifier: AGPL-3.0-or-later
import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = { title: "Setup guide" };

export default function Setup() {
  return <>
    <div className="page-head"><div>
      <h1>Connect your computer and phone.</h1>
      <p className="lede">You need an Android phone and a Windows or Linux computer. Use the same account on the website and both apps. You do not need a server or Tailscale.</p>
    </div></div>
    <div className="guide">
      <nav className="guide-nav" aria-label="On this page">
        <p>On this page</p>
        <a href="#activate">Get Cloud access</a><a href="#install">Install both apps</a><a href="#computer">Your computer</a>
        <a href="#phone">Connect your phone</a><a href="#share">First share</a><a href="#webcam">Phone as webcam</a><a href="#help">If setup stops</a>
      </nav>
      <div>
        <ol className="timeline">
          <li id="activate"><h2>Get Cloud access</h2>
            <p><Link href="/account">Open your account</Link> to start an available free trial, subscribe, or activate an invitation code. If your access is already active, go straight to downloads.</p>
            <p>Signing in gives you an account. You still approve each device on your computer before it can share content.</p>
          </li>
          <li id="install"><h2>Install on your computer and phone</h2>
            <p>Download the Windows or Linux app and Android APK from your account. Install both: these builds include the connection settings. Keep this guide open while you switch to the apps.</p>
            <p>Windows beta installers do not yet have a trusted publisher signature. Check the supplied checksum before installing. If you already use Saiph, read the upgrade instructions first: uninstalling or clearing app data can remove your keys and pairing.</p>
          </li>
          <li id="computer"><h2>Start on your computer</h2>
            <p>Open Saiph → <b>Phone</b>. Choose <b>Continue with Google</b> and use the account with Cloud access, then return to Saiph. Choose <b>Set up this computer</b> to make it your main computer.</p>
            <p>Your main computer approves your other devices and renews their access. Keep it online regularly; syncing stops after 12 hours without renewal.</p>
            <details className="more"><summary>Already have a main computer?</summary>
              <p>Choose <b>Join as another computer</b> instead. Follow the in-app instructions and approve the new computer on your main one. Add phones from your main computer’s Phone tab.</p>
            </details>
          </li>
          <li id="phone"><h2>Find, compare and approve</h2>
            <p><b>On your computer:</b> keep Phone open. If you already have a phone connected, choose <b>Add a device</b>.</p>
            <p><b>On your phone:</b> open Saiph, review the privacy and terms, and choose <b>Continue with Google</b> using the same account. On the same Wi-Fi, tap <b>Find my computer</b>. Compare the six-digit code on both screens, then confirm on the phone and choose <b>Codes match, approve</b> on the computer.</p>
            <p><b>Using the QR code instead?</b> Tap <b>Scan QR code</b> on your phone and scan the computer’s QR. Compare every group of the computer’s security code before trusting it. The phone’s request then appears on the computer: choose <b>Review and approve</b>, compare the phone’s full security code, give it a name and approve it.</p>
            <p>If any code differs, cancel. Keep both apps open until the computer says <b>Phone connected</b>. Signing in alone never approves a device.</p>
            <details className="more"><summary>Cannot scan, or the phone does not appear?</summary>
              <p>On the computer, open <b>Can’t scan? Copy a code instead</b>. On the phone, open <b>Paste a code instead</b>. For a missing request, use <b>Phone not appearing?</b> on the phone and <b>My device hasn’t appeared</b> on the computer. Compare the full security codes before approval.</p>
            </details>
          </li>
          <li id="share"><h2>Try your first share</h2>
            <p>In Saiph on your phone, choose <b>Send a file</b> and select a small, harmless file. On the computer, open <b>Phone → Files</b> and check that it arrives.</p>
            <p>Choose photos, notifications, texts and calls during the phone’s sharing setup. Each is optional: choose <b>Not now</b> to skip it and change it later in Settings. Android permissions and Saiph’s sharing switches both need to allow a feature.</p>
            <p>For photos, turn on photo sharing and choose the photos Android allows Saiph to read. For notifications, allow notification access in Android Settings. Texts and calls need their own phone permissions; call audio stays on your phone.</p>
            <p>Android can restrict background clipboard access and battery use. Follow the phone’s permission guidance, then test harmless clipboard text in both directions before relying on it.</p>
          </li>
        </ol>
        <section className="card" id="webcam" aria-labelledby="webcam-title">
          <h2 id="webcam-title">Optional: use your phone as a webcam</h2>
          <p>This is separate from connecting your account. Keep the phone and computer on the same Wi-Fi; camera video stays on your local network.</p>
          <ol>
            <li>On your computer, open <b>Phone → Webcam</b> and choose <b>Use phone as webcam</b>, or <b>Preview camera</b> to try it.</li>
            <li>On your phone, accept Saiph’s camera request and confirm with your screen lock. Or open <b>Use as webcam</b> on your phone, then accept on your computer or scan its camera code. Allow Android camera access when asked.</li>
            <li>When the preview appears, choose <b>Saiph Camera</b> in your meeting app. Stop the camera in Saiph when you finish.</li>
          </ol>
          <p>The integrated meeting-app webcam needs the Windows Saiph build. Camera preview works without that integration. If it is unavailable, follow the explanation in the app; installing debugging tools is not part of account setup.</p>
        </section>
        <section className="card" id="help"><h2>If setup stops</h2>
          <dl>
            <dt><b>Signed in, but no Cloud access?</b></dt><dd>Check <Link href="/account">your account</Link> for an active trial, subscription or invitation. Check that all three sign-ins use the same account.</dd>
            <dt><b>Computer not found on Wi-Fi?</b></dt><dd>Keep its Phone connection screen open. Try Scan QR code instead; both devices still need internet access.</dd>
            <dt><b>QR code expired?</b></dt><dd>Choose Refresh QR code on the computer and scan the new one.</dd>
            <dt><b>Approved, but not connected?</b></dt><dd>Keep Saiph open on the phone, turn on syncing and check internet access on both devices. Approval is saved; leaving the setup screen does not remove it.</dd>
            <dt><b>Permission denied?</b></dt><dd>Open Android Settings → Apps → Saiph → Permissions, then return to Saiph. Notification access has its own Android settings page. You can keep using features you have allowed.</dd>
          </dl>
          <p>For help, note the device, app version, step and error text. Keep invitation codes, approval codes, tokens and personal content out of public reports. <a href="https://usesaiph.com/contact.html">Contact support</a>.</p>
          <p>Keep your main computer’s keys: lost root-key recovery and transferring the root to another computer are not available yet.</p>
        </section>
        <div className="actions"><Link className="button" href="/account">Open your account and downloads</Link></div>
      </div>
    </div>
  </>;
}
