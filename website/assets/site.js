// SPDX-License-Identifier: AGPL-3.0-or-later
// Wires links and plan details from config.js into every page.
(function () {
  const cfg = window.ORION_SITE || {};
  const privacy = cfg.privacy || {};
  const waitlist = cfg.waitlist || {};
  const consent = "I agree to receive the Saiph launch announcement and occasional launch updates by email. I can unsubscribe or ask for my email to be deleted at any time.";
  const privacyFields = ["controllerName", "controllerCountry", "contactEmail", "updatedAt", "hostingRetention", "hostingTransfers", "contactProcessing"];
  const waitlistFields = ["processorName", "processorPrivacyUrl", "processingLocations", "transferSafeguards", "retention", "withdrawal", "noticeVersion"];
  const complete = (value, fields) => fields.every((field) => typeof value[field] === "string" && value[field].trim());
  const privacyReady = privacy.status === "approved" && complete(privacy, privacyFields)
    && /^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/.test(privacy.contactEmail);
  const waitlistReady = privacyReady && complete(waitlist, waitlistFields)
    && /^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/.test(waitlist.noticeVersion)
    && cfg.waitlistUrl === "https://tally.so/r/gDy42K?consent_version=" + waitlist.noticeVersion
    && cfg.waitlistPrivacyUrl === "privacy.html#waitlist"
    && waitlist.processorName === "Tally" && waitlist.processorPrivacyUrl === "https://tally.so/help/privacy-policy"
    && waitlist.consentText === consent && cfg.waitlistNotice === consent && waitlist.optInMode === "single"
    && ["emailRequired", "consentRequired", "partialSubmissionsDisabled", "confirmationEmailDisabled", "trackingDisabled"].every((field) => waitlist[field] === true);

  function link(a, url, unavailable) {
    if (url) {
      a.href = url;
      a.removeAttribute("aria-disabled");
      a.removeAttribute("tabindex");
      return;
    }
    a.removeAttribute("href");
    a.setAttribute("aria-disabled", "true");
    a.setAttribute("tabindex", "-1");
    a.title = unavailable;
  }

  document.querySelectorAll('[data-link="github"]').forEach((a) => {
    link(a, cfg.githubUrl, "Public source coming soon");
    if (cfg.githubUrl && cfg.sourceVisibility !== "public") {
      a.title = "Private repository: invited GitHub collaborators only";
      a.setAttribute("aria-label", "GitHub: private repository, invited collaborators only");
    }
  });
  document.querySelectorAll("[data-source-notice]").forEach((el) => {
    el.textContent = cfg.sourceVisibility === "public"
      ? "Source is available on GitHub."
      : "The GitHub repository is private for now.";
  });
  const betaUrl = /^https:\/\/appdistribution\.firebase\.dev\/i\/[A-Za-z0-9]{8,64}$/.test(cfg.androidBetaUrl || "") ? cfg.androidBetaUrl : "";
  document.querySelectorAll("[data-android-beta]").forEach((el) => { el.hidden = !betaUrl; });
  document.querySelectorAll('[data-link="android-beta"]').forEach((a) => link(a, betaUrl, "Android beta invitations are not open"));
  const betaAccountUrl = /^https:\/\/[a-z0-9.-]+\/account$/.test(cfg.betaAccountUrl || "") ? cfg.betaAccountUrl : "";
  document.querySelectorAll("[data-beta-access]").forEach((el) => { el.hidden = !betaAccountUrl; });
  document.querySelectorAll('[data-link="beta-account"]').forEach((a) => link(a, betaAccountUrl, "Beta access invitations are not open"));
  document.querySelectorAll('[data-link="releases"]').forEach((a) => link(a, cfg.releasesUrl, "Releases coming soon"));
  // With subscriptions open, installers for every platform are in the subscriber's account.
  const subscribeUrl = /^https:\/\/[a-z0-9.-]+\/account$/.test(cfg.subscribeUrl || "") ? cfg.subscribeUrl : "";
  document.querySelectorAll("[data-download]").forEach((a) => {
    const fromAccount = (["windows", "linux", "android"].includes(a.dataset.download) && subscribeUrl)
      || (["windows", "linux"].includes(a.dataset.download) && betaAccountUrl);
    const url = cfg.downloads && cfg.downloads[a.dataset.download] || fromAccount;
    link(a, url, "Download coming soon");
    const go = a.querySelector(".go");
    if (fromAccount && go && !(cfg.downloads && cfg.downloads[a.dataset.download])) {
      go.textContent = subscribeUrl ? "Download from your account →" : "Get beta access";
    }
    if (!url && go) {
      go.textContent = "Coming soon";
      go.classList.add("muted");
    }
  });

  document.querySelectorAll('[data-link="subscribe"]').forEach((a) => {
    if (subscribeUrl) {
      link(a, subscribeUrl);
      a.textContent = a.dataset.liveText || "Subscribe";
    } else if (waitlistReady) {
      link(a, "waitlist.html");
      a.textContent = "Join the early-access list";
      const notice = document.createElement("p");
      notice.className = "muted";
      notice.appendChild(document.createTextNode(cfg.waitlistNotice || "Read how your email will be used. "));
      if (cfg.waitlistPrivacyUrl) {
        const privacy = document.createElement("a");
        privacy.href = cfg.waitlistPrivacyUrl;
        privacy.textContent = " Privacy information";
        notice.appendChild(privacy);
      }
      a.insertAdjacentElement("afterend", notice);
    } else if (betaAccountUrl) {
      // Until signup or payment opens, early access is invite-only beta access.
      // Its front page explains the invitation before asking anyone to sign in.
      link(a, betaAccountUrl.replace(/\/account$/, "/"));
      a.textContent = "Get beta access";
      const notice = document.createElement("p");
      notice.className = "muted beta-note";
      notice.appendChild(document.createTextNode("Invite only for now: you'll need an invitation code."));
      // In a row of buttons the note goes under the whole row.
      const row = a.parentElement && a.parentElement.classList && a.parentElement.classList.contains("btn-row") ? a.parentElement : a;
      row.insertAdjacentElement("afterend", notice);
    } else {
      const publicSource = cfg.githubUrl && cfg.sourceVisibility === "public";
      link(a, publicSource ? cfg.githubUrl : "", "Hosted early access is not open yet");
      a.textContent = publicSource ? "Follow progress on GitHub" : "Early access coming soon";
    }
  });
  // The Hosted plan's label says what is open now.
  document.querySelectorAll("[data-hosted-status]").forEach((el) => {
    if (subscribeUrl) el.textContent = el.dataset.liveText || "Available now";
    else if (!waitlistReady && betaAccountUrl) el.textContent = el.dataset.betaText || "Invite-only beta";
  });
  document.querySelectorAll("[data-hosted-live]").forEach((el) => { el.hidden = !subscribeUrl; });
  document.querySelectorAll("[data-hosted-soon]").forEach((el) => { el.hidden = Boolean(subscribeUrl); });

  const price = subscribeUrl && cfg.hostedPrice;
  document.querySelectorAll("[data-price]").forEach((el) => {
    el.textContent = price || "Early access";
    const period = document.createElement("small");
    period.textContent = price ? cfg.hostedPeriod || "" : "pricing at launch";
    el.appendChild(document.createTextNode(" "));
    el.appendChild(period);
  });
  document.querySelectorAll("[data-price-note]").forEach((el) => {
    el.textContent = price && cfg.hostedPriceNote || "";
    el.hidden = !el.textContent;
  });
  document.querySelectorAll("[data-license]").forEach((el) => {
    el.textContent = (cfg.license && cfg.license[el.dataset.license]) || "";
  });

  function fill(selector, value) {
    document.querySelectorAll(selector).forEach((el) => { el.textContent = value || ""; });
  }
  document.querySelectorAll("[data-privacy-draft]").forEach((el) => { el.hidden = privacyReady; });
  document.querySelectorAll("[data-privacy-approved]").forEach((el) => { el.hidden = !privacyReady; });
  document.querySelectorAll("[data-waitlist-details]").forEach((el) => { el.hidden = !waitlistReady; });
  document.querySelectorAll("[data-waitlist-inactive]").forEach((el) => { el.hidden = waitlistReady; });
  if (privacyReady) fill("[data-privacy-basis]", "The purpose is website delivery, reliability and abuse prevention. The lawful basis is legitimate interests in operating a secure website.");
  if (privacy.controllerName) fill("[data-privacy-controller]", privacy.controllerName);
  if (privacy.controllerCountry) fill("[data-privacy-country]", privacy.controllerCountry);
  fill("[data-privacy-date]", privacy.updatedAt);
  fill("[data-privacy-hosting-retention]", privacy.hostingRetention);
  fill("[data-privacy-hosting-transfers]", privacy.hostingTransfers);
  fill("[data-privacy-contact-processing]", privacy.contactProcessing);
  document.querySelectorAll("[data-privacy-contact]").forEach((el) => {
    if (privacyReady) { el.href = "mailto:" + privacy.contactEmail; el.textContent = privacy.contactEmail; }
  });
  fill("[data-waitlist-processor]", waitlist.processorName);
  fill("[data-waitlist-consent]", waitlist.consentText);
  fill("[data-waitlist-locations]", waitlist.processingLocations);
  fill("[data-waitlist-transfers]", waitlist.transferSafeguards);
  fill("[data-waitlist-retention]", waitlist.retention);
  fill("[data-waitlist-withdrawal]", waitlist.withdrawal);
  if (waitlistReady) fill("[data-waitlist-status]", "Read how your email is used, then enter it and tick the consent checkbox on Tally. No confirmation email is sent.");
  document.querySelectorAll('[data-link="waitlist"]').forEach((a) => link(a, waitlistReady ? cfg.waitlistUrl : "", "Email signup is not open yet"));
  document.querySelectorAll('[data-link="processor-privacy"]').forEach((a) => link(a, waitlistReady ? waitlist.processorPrivacyUrl : "", "Provider information is not activated yet"));
  const release = cfg.release || {};
  const releaseReady = cfg.sourceVisibility === "public" && Boolean(cfg.releasesUrl) && Boolean(release.sourceCommit);
  if (subscribeUrl && !releaseReady) fill("[data-release-status]", "Installers for Windows, Linux and Android are in your Saiph account. Subscribe to Saiph Hosted or activate an invitation code, then download them there. No compilation or personal server is required.");
  else if (betaAccountUrl && !releaseReady) fill("[data-release-status]", "Beta installers are available from your Saiph account. Sign in and activate your invitation code. No compilation or personal server is required.");
  document.querySelectorAll("[data-release-details]").forEach((el) => { el.hidden = !releaseReady; });
  if (releaseReady) fill("[data-release-status]", "Downloads are pinned to " + release.tag + ". Read the release notes and verify your download before installing.");
  fill("[data-release-tag]", release.tag);
  fill("[data-release-commit]", release.sourceCommit);
  const releaseLinks = {checksums: release.checksumsUrl, "source-metadata": release.sourceMetadataUrl,
    "release-source": releaseReady ? cfg.githubUrl + "/tree/" + release.sourceCommit : ""};
  Object.entries(releaseLinks).forEach(([name, url]) => {
    document.querySelectorAll('[data-link="' + name + '"]').forEach((a) => link(a, releaseReady ? url : "", "Release not available yet"));
  });

  const year = document.querySelector("[data-year]");
  if (year) year.textContent = new Date().getFullYear();
})();
