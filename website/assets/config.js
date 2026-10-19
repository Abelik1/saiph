// SPDX-License-Identifier: AGPL-3.0-or-later
// Site settings. Edit these instead of the HTML.
window.ORION_SITE = {
  sourceVisibility: "private",
  githubUrl: "",
  // Keep source and release links empty until publication and artifacts are approved.
  releasesUrl: "",
  betaAccountUrl: "", // Authenticated beta access portal; independent of public releases.
  release: {}, // Generated from real artifact bytes and GitHub metadata.
  downloads: {
    windows: "", // e.g. ".../releases/download/v0.1.0/Saiph-Link-0.1.0-windows-x86_64.exe"
    linux: "",   // e.g. ".../releases/download/v0.1.0/Saiph-Link-0.1.0-linux-x86_64.tar.gz"
    android: "", // e.g. ".../releases/download/v0.1.0/orion-android-0.1.0.apk"
    server: ""   // e.g. ".../releases/download/v0.1.0/orion-server-0.1.0.tar.gz"
  },
  // Cloud plan. Leave subscribeUrl empty until billing is live. It is the account
  // site's /account page; never a Stripe Payment Link (docs/PAID_HOSTED.md).
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
  hostedTrial: "", // e.g. "Free for 14 days, no card needed"; only while the account site offers trials
  hostedYearlyPrice: "", // e.g. "€89.99"
  ga4: { measurementId: "" }, // Owner's GA4 web stream ID ("G-..."); empty keeps Google Analytics and the cookie banner off.
  // Off by default. Variants map to Stripe prices held in the account site's SAIPH_PRICE_TEST.
  priceTest: { enabled: false, id: "", variants: {} }, // e.g. {b: {monthly: "€7.99", yearly: "€69.99"}}
  license: {
    core: "AGPL-3.0-or-later", // desktop app + Hub
    android: "GPL-3.0-only"  // retained upstream grant: Sefirah-Android fork
  }
};
