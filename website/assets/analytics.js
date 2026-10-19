// SPDX-License-Identifier: AGPL-3.0-or-later
// Public landing pageviews, allow-listed campaign tags and a fixed set of button
// counts. Activation belongs to the reviewed site build (website/ANALYTICS.md).
(function () {
  const cfg = window.ORION_SITE || {};
  const settings = cfg.analytics || {};
  const privacy = cfg.privacy || {};
  const origins = new Set(["https://usesaiph.com", "https://www.usesaiph.com"]);
  const pages = new Set(["/", "/index.html", "/self-host.html", "/hosted.html", "/downloads.html",
    "/waitlist.html", "/privacy.html", "/account-privacy.html", "/terms.html", "/refunds.html", "/contact.html"]);
  const privacyFields = ["controllerName", "controllerCountry", "contactEmail", "updatedAt",
    "hostingRetention", "hostingTransfers", "contactProcessing"];
  const ready = settings.enabled === true && privacy.status === "approved"
    && privacyFields.every((key) => typeof privacy[key] === "string" && privacy[key].trim())
    && /^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/.test(privacy.contactEmail)
    && typeof settings.scriptPath === "string"
    && /^\/(?:_vercel\/insights|[A-Za-z0-9_-]{8,128})\/script\.js$/.test(settings.scriptPath);

  // Campaign tags kept on pageviews. Values must be on these lists (or, for
  // utm_content, an ad ID like "01-ecosystem-convenience"); everything else in a
  // query is dropped. Add a new campaign here in a reviewed source change.
  const campaign = {
    utm_source: new Set(["reddit", "x", "facebook", "instagram", "linkedin", "youtube", "tiktok", "discord",
      "mastodon", "bluesky", "hackernews", "producthunt", "github", "newsletter", "google", "bing"]),
    utm_medium: new Set(["social", "paid_social", "cpc", "email", "referral", "community", "video"]),
    utm_campaign: new Set(["2026-10-launch"]),
    utm_content: /^[0-9]{2}(?:-[a-z]{2,20}){1,4}$/,
  };
  // The only custom events, each with at most one property from a fixed list.
  const events = {
    download_click: { platform: new Set(["windows", "linux", "android", "android_apk", "server"]) },
    cloud_click: {},
    // Start your free trial (landing page main button, or the Cloud page with trials on).
    trial_click: {},
    // Buy now on the landing page or a plan button on the Cloud page.
    buy_click: { plan: new Set(["monthly", "yearly"]) },
    account_click: {},
    github_click: {},
  };

  function campaignQuery(url) {
    const kept = [];
    Object.keys(campaign).forEach((key) => {
      const value = url.searchParams.get(key);
      const allowed = campaign[key];
      if (value && (allowed instanceof Set ? allowed.has(value) : allowed.test(value))) kept.push(key + "=" + value);
    });
    return kept.length ? "?" + kept.join("&") : "";
  }

  function publicUrl(value, withCampaign) {
    try {
      const url = new URL(value);
      if (!origins.has(url.origin) || url.origin !== window.location.origin
          || url.username || url.password || !pages.has(url.pathname)) return null;
      // Never send fragments, tokens, emails or other query values; only
      // allow-listed campaign tags survive, and only on pageviews.
      return url.origin + url.pathname + (withCampaign ? campaignQuery(url) : "");
    } catch (_) { return null; }
  }

  function eventPayload(payload) {
    if (!payload || typeof payload !== "object" || !Object.prototype.hasOwnProperty.call(events, payload.name)) return null;
    const allowed = events[payload.name];
    const data = payload.data == null ? {} : payload.data;
    if (typeof data !== "object" || Array.isArray(data)) return null;
    const keys = Object.keys(data);
    if (keys.some((key) => !Object.prototype.hasOwnProperty.call(allowed, key) || !allowed[key].has(data[key]))) return null;
    const clean = {};
    keys.forEach((key) => { clean[key] = data[key]; });
    return keys.length ? { name: payload.name, data: clean } : { name: payload.name };
  }

  function safeReferrer() {
    if (!document.referrer) return true;
    try {
      const url = new URL(document.referrer);
      if (url.protocol !== "https:" || url.username || url.password || url.search || url.hash) return false;
      // The provider reads referrer independently of beforeSend. Skip collection
      // if it includes a path we cannot establish as public.
      return url.origin === window.location.origin ? pages.has(url.pathname) : url.pathname === "/";
    } catch (_) { return false; }
  }

  // Missing configuration, localhost, account hosts, protected preview aliases,
  // sensitive routes and unsafe referrers never load the provider script.
  const enabled = ready && publicUrl(window.location.href) !== null && safeReferrer()
    && window.navigator.globalPrivacyControl !== true && window.navigator.doNotTrack !== "1";
  document.querySelectorAll("[data-analytics-status]").forEach((element) => {
    element.textContent = enabled ? "Cookie-free visit analytics is enabled." : "Visit analytics is off for this visit.";
  });
  if (!enabled || window.saiphAnalyticsLoaded) return;
  window.saiphAnalyticsLoaded = true;
  window.va = window.va || function () { (window.vaq = window.vaq || []).push(arguments); };
  window.va("beforeSend", (event) => {
    if (!event || !safeReferrer()) return null;
    // Reconstruct the event rather than forwarding unknown payload/identity data.
    // The provider keeps its original payload when none is returned, so custom
    // events always return the checked payload explicitly.
    if (event.type === "pageview") {
      const url = publicUrl(event.url, true);
      return url ? { type: "pageview", url } : null;
    }
    if (event.type === "event") {
      const url = publicUrl(event.url, false);
      const payload = eventPayload(event.payload);
      return url && payload ? { type: "event", url, payload } : null;
    }
    return null;
  });
  // Button counts: which link was followed, never who followed it or where to.
  function clicked(link) {
    if (!link.hasAttribute("href")) return null;
    const download = link.dataset.download;
    if (download) return ["download_click", { platform: download === "android" ? "android_apk" : download }];
    switch (link.dataset.link) {
      case "android-beta": return ["download_click", { platform: "android" }];
      case "trial-start": return ["trial_click"];
      case "subscribe": return link.dataset.trialPath && link.href.endsWith("/trial") ? ["trial_click"] : ["cloud_click"];
      case "buy": {
        const checked = document.querySelector('[data-plan-picker] input[name="plan"]:checked');
        return ["buy_click", { plan: link.dataset.plan || (checked ? checked.value : "monthly") }];
      }
      case "account": case "beta-account": return ["account_click"];
      case "github": return ["github_click"];
      default: return null;
    }
  }
  document.addEventListener("click", (event) => {
    const target = event.target;
    const link = target && typeof target.closest === "function" ? target.closest("a[data-download], a[data-link]") : null;
    const found = link && clicked(link);
    if (!found || !eventPayload({ name: found[0], data: found[1] })) return;
    window.va("event", found[1] ? { name: found[0], data: found[1] } : { name: found[0] });
  }, true);
  const script = document.createElement("script");
  script.defer = true;
  script.src = settings.scriptPath;
  script.dataset.viewEndpoint = settings.scriptPath.replace(/script\.js$/, "view");
  script.dataset.eventEndpoint = settings.scriptPath.replace(/script\.js$/, "event");
  document.head.appendChild(script);
})();
