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
  document.querySelectorAll('[data-link="android-beta"]').forEach((a) => {
    link(a, betaUrl, "Android beta invitations are not open");
    if (betaUrl) a.dataset.signin = "firebase";
  });
  const betaAccountUrl = /^https:\/\/[a-z0-9.-]+\/account$/.test(cfg.betaAccountUrl || "") ? cfg.betaAccountUrl : "";
  document.querySelectorAll("[data-beta-access]").forEach((el) => { el.hidden = !betaAccountUrl; });
  document.querySelectorAll('[data-link="beta-account"]').forEach((a) => link(a, betaAccountUrl, "Beta access invitations are not open"));
  document.querySelectorAll('[data-link="releases"]').forEach((a) => link(a, cfg.releasesUrl, "Releases coming soon"));
  // With subscriptions open, installers for every platform are in the subscriber's account.
  const subscribeUrl = /^https:\/\/[a-z0-9.-]+\/account$/.test(cfg.subscribeUrl || "") ? cfg.subscribeUrl : "";
  document.querySelectorAll('[data-link="account"]').forEach((a) => {
    link(a, subscribeUrl || betaAccountUrl, "Account sign-in is not available yet");
  });
  document.querySelectorAll("[data-download]").forEach((a) => {
    const fromAccount = (["windows", "linux", "android"].includes(a.dataset.download) && subscribeUrl)
      || (["windows", "linux"].includes(a.dataset.download) && betaAccountUrl);
    const url = cfg.downloads && cfg.downloads[a.dataset.download] || fromAccount;
    link(a, url, "Download coming soon");
    if (url && url === fromAccount) a.dataset.signin = "account";
    const go = a.querySelector(".go");
    if (fromAccount && go && !(cfg.downloads && cfg.downloads[a.dataset.download])) {
      go.textContent = subscribeUrl ? "Download from your account →" : "Get beta access";
    }
    if (!url && go) {
      go.textContent = "Coming soon";
      go.classList.add("muted");
    }
  });

  // A free trial is started on the account page; the site only says it is offered.
  const trial = subscribeUrl && typeof cfg.hostedTrial === "string" ? cfg.hostedTrial : "";
  document.querySelectorAll("[data-trial]").forEach((el) => { el.textContent = trial; el.hidden = !trial; });
  // With trials on, Start your free trial is the main button (docs/LANDING_CONVERSION.md):
  // the account site's /trial signs in and starts the trial; Buy now steps back.
  const trialUrl = trial ? subscribeUrl.replace(/\/account$/, "/trial") : "";
  document.querySelectorAll("[data-trial-shown]").forEach((el) => { el.hidden = !trial; });
  document.querySelectorAll('[data-link="trial-start"]').forEach((a) => link(a, trialUrl, "Free trials are not open"));
  if (trial) document.querySelectorAll(".buy-now").forEach((a) => { if (a.classList) a.classList.remove("primary"); });

  // Buy now: the chosen plan (and price-test variant, when one runs) goes
  // straight to the account site's sign-in, which hands over to Stripe Checkout.
  const offer = (window.saiphConsent && window.saiphConsent.offer) || {variant: "a", test: null, inTest: false};
  const priceText = (value) => typeof value === "string" && /^€[1-9][0-9]{0,2}(\.[0-9]{2})?$/.test(value) ? value : "";
  const variantPrices = offer.variant !== "a" && cfg.priceTest && cfg.priceTest.variants && cfg.priceTest.variants[offer.variant] || {};
  const prices = {
    monthly: priceText(variantPrices.monthly) || (subscribeUrl && priceText(cfg.hostedPrice)) || "€9.99",
    yearly: priceText(variantPrices.yearly) || (subscribeUrl && priceText(cfg.hostedYearlyPrice)) || "€89.99",
  };
  const euros = (value) => Number(value.slice(1));
  const money = (amount) => "€" + amount.toFixed(2);
  const shownVariant = offer.variant !== "a" && priceText(variantPrices.monthly) && priceText(variantPrices.yearly);
  if (shownVariant) {
    document.querySelectorAll("[data-plan-price]").forEach((el) => { el.textContent = prices[el.dataset.planPrice] || el.textContent; });
    document.querySelectorAll("[data-plan-per-month]").forEach((el) => { el.textContent = money(euros(prices.yearly) / 12); });
    document.querySelectorAll("[data-plan-saving]").forEach((el) => {
      el.textContent = Math.round((1 - euros(prices.yearly) / (12 * euros(prices.monthly))) * 100) + "%";
    });
  }
  document.querySelectorAll("[data-price-test-note]").forEach((el) => { el.hidden = !shownVariant; });
  function buyUrl(plan) {
    if (!subscribeUrl || (plan !== "monthly" && plan !== "yearly")) return "";
    // The variant goes along only when this page shows its prices.
    const query = offer.test && offer.inTest && (offer.variant === "a" || shownVariant) ? "?offer=" + offer.variant : "";
    return subscribeUrl.replace(/\/account$/, "/buy/" + plan) + query;
  }
  function chosenPlan() {
    const checked = document.querySelector && document.querySelector('[data-plan-picker] input[name="plan"]:checked');
    return checked ? checked.value : "monthly";
  }
  function showPlan() {
    const plan = chosenPlan();
    document.querySelectorAll("[data-plan-picker] .plan").forEach((card) => {
      if (card.classList) card.classList.toggle("selected", card.dataset.plan === plan);
    });
    document.querySelectorAll("[data-buy-summary]").forEach((el) => {
      el.textContent = prices[plan] + " today, then every " + (plan === "yearly" ? "year" : "month") + ". No VAT is added.";
    });
    document.querySelectorAll('[data-link="buy"]').forEach((a) => {
      if (subscribeUrl) link(a, buyUrl(a.dataset.plan || plan));
    });
  }
  document.querySelectorAll("[data-plan-picker]").forEach((picker) => {
    if (picker.addEventListener) picker.addEventListener("change", showPlan);
  });
  if (subscribeUrl) showPlan();
  if (document.addEventListener) document.addEventListener("click", (event) => {
    const a = event.target.closest && event.target.closest('a[data-link="buy"], a[data-link="trial-start"], a[data-link="subscribe"][data-trial-path]');
    if (!a || !a.hasAttribute("href") || !window.saiphConsent) return;
    if (a.dataset.link !== "buy") { if (trial) window.saiphConsent.track("trial_click"); }
    else window.saiphConsent.track("buy_click", {plan: a.dataset.plan || chosenPlan()});
  });

  // Until subscriptions open, Buy buttons fall back to what Subscribe offers.
  [...document.querySelectorAll('[data-link="subscribe"]'), ...(subscribeUrl ? [] : document.querySelectorAll('[data-link="buy"]'))].forEach((a) => {
    if (subscribeUrl) {
      link(a, trial && a.dataset.trialPath === "/trial" ? trialUrl : subscribeUrl);
      a.textContent = (trial && a.dataset.trialText) || a.dataset.liveText || "Subscribe";
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
      link(a, publicSource ? cfg.githubUrl : "", "Cloud early access is not open yet");
      a.textContent = publicSource ? "Follow progress on GitHub" : "Early access coming soon";
    }
  });
  // The Cloud plan's label says what is open now.
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
  if (subscribeUrl && !releaseReady) fill("[data-release-status]", "Installers for Windows, Linux and Android are in your Saiph account. Subscribe to Saiph Cloud or activate an invitation code, then download them there. No compilation or personal server is required.");
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

  // Downloads that start with a sign-in say so before leaving the site.
  const signInNotes = {
    account: {title: "Sign in to download",
      body: "Saiph's installers are in your Saiph account. Next you'll sign in with Google, then choose your download on your account page.",
      go: "Continue to sign in"},
    firebase: {title: "Get the Android beta",
      body: "The Android app installs through Firebase App Distribution. Google will ask you to sign in so it can send you the beta invitation and updates.",
      go: "Continue to Google"}
  };
  let signInDialog;
  function askToSignIn(a, note) {
    if (!signInDialog) {
      signInDialog = document.createElement("dialog");
      signInDialog.className = "signin-dialog";
      signInDialog.setAttribute("aria-labelledby", "signin-title");
      signInDialog.setAttribute("aria-describedby", "signin-body");
      const title = document.createElement("h2");
      title.id = "signin-title";
      const body = document.createElement("p");
      body.id = "signin-body";
      body.className = "muted";
      const row = document.createElement("div");
      row.className = "btn-row";
      const go = document.createElement("a");
      go.className = "btn primary";
      const cancel = document.createElement("button");
      cancel.type = "button";
      cancel.className = "btn";
      cancel.textContent = "Cancel";
      cancel.addEventListener("click", () => signInDialog.close());
      row.append(go, cancel);
      signInDialog.append(title, body, row);
      // A click on the backdrop lands on the dialog itself.
      signInDialog.addEventListener("click", (event) => { if (event.target === signInDialog) signInDialog.close(); });
      document.body.appendChild(signInDialog);
    }
    signInDialog.querySelector("h2").textContent = note.title;
    signInDialog.querySelector("p").textContent = note.body;
    const go = signInDialog.querySelector("a");
    go.textContent = note.go;
    go.href = a.href;
    go.rel = a.rel || "";
    signInDialog.showModal();
    go.focus();
  }
  if (document.addEventListener) document.addEventListener("click", (event) => {
    const a = event.target.closest && event.target.closest("a[data-signin]");
    const note = a && a.href && signInNotes[a.dataset.signin];
    if (!note || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    if (typeof HTMLDialogElement !== "function") return;
    event.preventDefault();
    askToSignIn(a, note);
  });

  const year = document.querySelector("[data-year]");
  if (year) year.textContent = new Date().getFullYear();
})();
