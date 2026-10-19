// SPDX-License-Identifier: AGPL-3.0-or-later
// Cookie choice, Google Analytics 4 (Consent Mode v2, basic mode) and the
// optional price test. Nothing is loaded from Google and nothing is stored on
// the device until the visitor presses Accept (docs/LANDING_CONVERSION.md,
// website/ANALYTICS.md). Declining is one press, like accepting.
(function () {
  const cfg = window.ORION_SITE || {};
  const ga = cfg.ga4 || {};
  const test = cfg.priceTest || {};
  const MEASUREMENT_ID = /^G-[A-Z0-9]{4,16}$/.test(ga.measurementId || "") ? ga.measurementId : "";
  // Google is contacted only from the production pages; previews and local
  // builds can show the banner but never load the tag.
  const PRODUCTION = new Set(["https://usesaiph.com", "https://www.usesaiph.com"]);
  const COOKIE = "saiph_consent";
  const SIX_MONTHS = 182 * 86400; // DPC: ask again after at most six months.
  const TEST_KEY = "saiph_price_test";
  const TEST_DAYS = 90;
  const VARIANT = /^[a-d]$/;
  const loc = window.location || {};
  const production = PRODUCTION.has(loc.origin);
  // One cookie on usesaiph.com so the account site honours the same choice.
  const cookieDomain = production ? "; Domain=usesaiph.com" : "";
  const browserOptOut = window.navigator && (window.navigator.globalPrivacyControl === true || window.navigator.doNotTrack === "1");

  function readChoice() {
    const match = (document.cookie || "").match(/(?:^|;\s*)saiph_consent=v1\.(granted|denied)\.(\d{10})(?:;|$)/);
    if (!match) return null;
    // A choice older than six months is asked again.
    return Date.now() / 1000 - Number(match[2]) < SIX_MONTHS ? match[1] : null;
  }
  function writeChoice(value) {
    document.cookie = COOKIE + "=v1." + value + "." + Math.floor(Date.now() / 1000) + "; Max-Age=" + SIX_MONTHS
      + "; Path=/" + cookieDomain + "; SameSite=Lax" + (loc.protocol === "https:" ? "; Secure" : "");
  }
  function clearGoogleCookies() {
    (document.cookie || "").split(";").forEach((part) => {
      const name = part.split("=")[0].trim();
      if (name === "_ga" || /^_ga_[A-Z0-9]+$/.test(name)) {
        ["", "; Domain=usesaiph.com", "; Domain=" + (loc.hostname || "")].forEach((domain) => {
          document.cookie = name + "=; Max-Age=0; Path=/" + domain;
        });
      }
    });
  }
  function storage() {
    try { return window.localStorage; } catch (_) { return null; }
  }

  let choice = browserOptOut ? "denied" : readChoice();

  // Price test: random, sticky and shown before purchase. Without consent
  // nothing is stored, so a visitor is in the test only when the variant can be
  // kept: an earlier Accept (random draw) or a campaign link (?offer=b).
  const variants = test.enabled === true && /^[a-z0-9][a-z0-9-]{0,39}$/.test(test.id || "")
    && test.variants && typeof test.variants === "object"
    ? ["a"].concat(Object.keys(test.variants).filter((key) => VARIANT.test(key) && key !== "a")) : ["a"];
  const offer = { test: variants.length > 1 ? test.id : null, variant: "a", inTest: false };
  if (offer.test) {
    let stored = null;
    if (choice === "granted") {
      try { stored = JSON.parse((storage() && storage().getItem(TEST_KEY)) || "null"); } catch (_) { stored = null; }
    }
    let fromLink = null;
    try { fromLink = new URL(loc.href).searchParams.get("offer"); } catch (_) { fromLink = null; }
    if (stored && stored.id === offer.test && variants.includes(stored.variant)
        && typeof stored.at === "number" && Date.now() / 1000 - stored.at < TEST_DAYS * 86400) {
      offer.variant = stored.variant; offer.inTest = stored.inTest === true;
    } else if (fromLink && variants.includes(fromLink)) {
      offer.variant = fromLink; offer.inTest = true;
    } else if (choice === "granted") {
      const random = new Uint32Array(1);
      (window.crypto || {}).getRandomValues ? window.crypto.getRandomValues(random) : (random[0] = Math.floor(Math.random() * 4294967296));
      offer.variant = variants[random[0] % variants.length]; offer.inTest = true;
    }
  }
  function keepOffer() {
    // Only after Accept. A visitor who saw the standard price before choosing
    // keeps it and stays out of the test, so nobody sees a price change.
    if (!offer.test || choice !== "granted") return;
    try {
      const store = storage();
      const stored = JSON.parse((store && store.getItem(TEST_KEY)) || "null");
      if (!stored || stored.id !== offer.test) {
        store && store.setItem(TEST_KEY, JSON.stringify({ id: offer.test, variant: offer.variant, inTest: offer.inTest, at: Math.floor(Date.now() / 1000) }));
      }
    } catch (_) { /* Storage blocked: the price still stays for this page and its Buy link. */ }
  }
  keepOffer();

  // Campaign tags kept in the page address GA sees; everything else is dropped.
  function pageLocation() {
    try {
      const url = new URL(loc.href);
      const kept = new URLSearchParams();
      ["utm_source", "utm_medium", "utm_campaign", "utm_content"].forEach((key) => {
        const value = url.searchParams.get(key);
        if (value && /^[A-Za-z0-9._-]{1,64}$/.test(value)) kept.set(key, value);
      });
      const query = kept.toString();
      return url.origin + url.pathname + (query ? "?" + query : "");
    } catch (_) { return ""; }
  }

  let loaded = false;
  function gtag() { window.dataLayer.push(arguments); }
  function loadGoogle() {
    if (loaded || !MEASUREMENT_ID || !production || choice !== "granted") return;
    loaded = true;
    window.dataLayer = window.dataLayer || [];
    window.gtag = gtag;
    gtag("consent", "default", { ad_storage: "denied", ad_user_data: "denied", ad_personalization: "denied", analytics_storage: "denied" });
    gtag("consent", "update", { analytics_storage: "granted" });
    gtag("js", new Date());
    gtag("set", { allow_google_signals: false, allow_ad_personalization_signals: false });
    gtag("config", MEASUREMENT_ID, {
      cookie_domain: "usesaiph.com",
      cookie_expires: SIX_MONTHS,
      linker: { domains: ["usesaiph.com", "account.dev.usesaiph.com"] },
      page_location: pageLocation(),
      price_test: offer.test || undefined,
      price_variant: offer.test ? offer.variant : undefined,
    });
    const script = document.createElement("script");
    script.async = true;
    script.src = "https://www.googletagmanager.com/gtag/js?id=" + encodeURIComponent(MEASUREMENT_ID);
    document.head.appendChild(script);
  }

  // Funnel events. Names and parameters come from this fixed list only.
  const EVENTS = { buy_click: ["plan"], trial_click: [] };
  function track(name, params) {
    if (!loaded || !Object.prototype.hasOwnProperty.call(EVENTS, name)) return;
    const clean = { transport_type: "beacon" };
    EVENTS[name].forEach((key) => {
      if (params && (params[key] === "monthly" || params[key] === "yearly")) clean[key] = params[key];
    });
    if (offer.test && offer.inTest) { clean.price_test = offer.test; clean.price_variant = offer.variant; }
    gtag("event", name, clean);
  }

  let banner = null;
  function decide(value) {
    choice = value;
    writeChoice(value);
    if (value === "granted") { keepOffer(); loadGoogle(); }
    else {
      if (loaded) gtag("consent", "update", { analytics_storage: "denied" });
      clearGoogleCookies();
      try { storage() && storage().removeItem(TEST_KEY); } catch (_) { /* nothing stored */ }
    }
    // Keep keyboard focus somewhere sensible once the banner closes.
    const hadFocus = banner && banner.contains(document.activeElement);
    if (banner) banner.hidden = true;
    const opener = document.querySelector("[data-consent-open]");
    if (hadFocus && opener) opener.focus();
    document.querySelectorAll("[data-consent-status]").forEach((el) => { el.textContent = statusText(); });
  }
  function statusText() {
    return browserOptOut ? "Your browser asks sites not to track you, so Google Analytics stays off."
      : choice === "granted" ? "You accepted Google Analytics cookies on this browser."
      : choice === "denied" ? "You declined Google Analytics cookies on this browser." : "You have not chosen yet.";
  }
  function showBanner() {
    if (!banner) {
      banner = document.createElement("section");
      banner.className = "consent";
      banner.setAttribute("aria-labelledby", "consent-title");
      const text = document.createElement("p");
      text.id = "consent-title";
      text.appendChild(document.createTextNode("May we use Google Analytics cookies to see which pages help visitors and to test prices? "));
      const more = document.createElement("a");
      more.href = "privacy.html#cookies";
      more.textContent = "Details";
      text.appendChild(more);
      const row = document.createElement("div");
      row.className = "consent-buttons";
      [["Accept", "granted"], ["Decline", "denied"]].forEach(([label, value]) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "btn";
        button.textContent = label;
        button.addEventListener("click", () => decide(value));
        row.appendChild(button);
      });
      banner.append(text, row);
      document.body.appendChild(banner);
    }
    banner.hidden = false;
  }

  window.saiphConsent = {
    get granted() { return choice === "granted"; },
    offer,
    track,
  };
  if (!MEASUREMENT_ID || !document.addEventListener) return;
  loadGoogle();
  function ready() {
    // A browser privacy signal (GPC or Do Not Track) is treated as Decline.
    document.querySelectorAll("[data-consent-open]").forEach((button) => {
      button.hidden = browserOptOut;
      button.addEventListener("click", showBanner);
    });
    document.querySelectorAll("[data-consent-status]").forEach((el) => { el.textContent = statusText(); });
    if (choice === null) showBanner();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", ready);
  else ready();
})();
