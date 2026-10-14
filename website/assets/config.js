// SPDX-License-Identifier: AGPL-3.0-or-later
// Site settings. Edit these instead of the HTML.
window.ORION_SITE = {
  sourceVisibility: "private",
  githubUrl: "",
  // Keep source and release links empty until publication and artifacts are approved.
  releasesUrl: "",
  betaAccountUrl: "", // Authenticated friends-beta portal; independent of public releases.
  release: {}, // Generated from real artifact bytes and GitHub metadata.
  downloads: {
    windows: "", // e.g. ".../releases/download/v0.1.0/Saiph-Link-0.1.0-windows-x86_64.exe"
    linux: "",   // e.g. ".../releases/download/v0.1.0/Saiph-Link-0.1.0-linux-x86_64.tar.gz"
    android: "", // e.g. ".../releases/download/v0.1.0/orion-android-0.1.0.apk"
    server: ""   // e.g. ".../releases/download/v0.1.0/orion-server-0.1.0.tar.gz"
  },
  // Hosted plan. Leave subscribeUrl empty until billing is live (e.g. a Stripe Payment Link).
  // While it is empty, the button collects interest through waitlistUrl, or falls back to GitHub.
  subscribeUrl: "",
  waitlistUrl: "",  // Reviewed Tally URL with consent_version; empty until privacy/contact approval.
  waitlistPrivacyUrl: "", // Public information about email use and deletion requests.
  analytics: { enabled: false, scriptPath: "/_vercel/insights/script.js" }, // Activate only after dashboard and privacy review.
  privacy: {}, // Reviewed public controller/contact/hosting facts.
  waitlist: {}, // Reviewed Tally single opt-in controls, notice version, retention and tracking facts.
  waitlistNotice: "", // Visible beside each waitlist link before collecting emails.
  hostedPrice: "",  // e.g. "€6" — empty shows "Pricing at launch"
  hostedPeriod: "/ month",
  license: {
    core: "AGPL-3.0-or-later", // desktop app + Hub
    android: "GPL-3.0-only"  // retained upstream grant: Sefirah-Android fork
  }
};
