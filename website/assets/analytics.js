// SPDX-License-Identifier: AGPL-3.0-or-later
// Public landing pageviews only. Activation belongs to the reviewed site build.
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

  function publicUrl(value) {
    try {
      const url = new URL(value);
      if (!origins.has(url.origin) || url.origin !== window.location.origin
          || url.username || url.password || !pages.has(url.pathname)) return null;
      // Never send query values, campaign parameters, fragments, tokens or emails.
      return url.origin + url.pathname;
    } catch (_) { return null; }
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
    element.textContent = enabled ? "Cookie-free pageview analytics is enabled." : "Pageview analytics is off for this visit.";
  });
  if (!enabled || window.saiphAnalyticsLoaded) return;
  window.saiphAnalyticsLoaded = true;
  window.va = window.va || function () { (window.vaq = window.vaq || []).push(arguments); };
  window.va("beforeSend", (event) => {
    if (!event || event.type !== "pageview" || !safeReferrer()) return null;
    const url = publicUrl(event.url);
    // Reconstruct the event rather than forwarding unknown payload/identity data.
    return url ? { type: "pageview", url } : null;
  });
  const script = document.createElement("script");
  script.defer = true;
  script.src = settings.scriptPath;
  script.dataset.viewEndpoint = settings.scriptPath.replace(/script\.js$/, "view");
  script.dataset.eventEndpoint = settings.scriptPath.replace(/script\.js$/, "event");
  document.head.appendChild(script);
})();
