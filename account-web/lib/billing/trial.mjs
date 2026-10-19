// SPDX-License-Identifier: AGPL-3.0-or-later
// Free trial of Saiph Cloud on sign-up (docs/PAID_HOSTED.md). Every new account
// may start one trial, without a card. The trial is a time-limited Hosted grant
// pushed like a paid grant (grant "trial:<ref>"); it never touches Stripe.
import { createHmac, randomBytes } from "node:crypto";

/** Default length (owner request, 19 October 2026: "a free trial on sign up"). */
export const DEFAULT_TRIAL_DAYS = 14;
/** One push covers the whole trial: stays inside the 35-day grant roll window. */
export const MAX_TRIAL_DAYS = 30;
/** Stripe Checkout needs a trial end at least 48 hours ahead; a shorter remainder
 * is not carried into the subscription (the first payment is then taken at once). */
export const CARRY_MIN_SECONDS = 48 * 3600 + 600;

/** @typedef {{days: number, cap: number | null, secret: string}} TrialConfig */

/**
 * `SAIPH_TRIAL_DAYS` (default 14, `0` turns trials off, at most 30),
 * `SAIPH_TRIAL_CAP` (unset: no cap; a whole number: at most that many trials ever,
 * for example 100 for "the first 100 people") and `SAIPH_TRIAL_SECRET` (32+
 * URL-safe characters keying the email hash). Trials are off without the secret.
 * @param {Record<string, string | undefined>} env
 * @returns {{config: TrialConfig | null, problems: string[]}}
 */
export function checkTrialConfig(env) {
  const problems = [];
  const daysText = env.SAIPH_TRIAL_DAYS?.trim() ?? "";
  const days = daysText === "" ? DEFAULT_TRIAL_DAYS : /^\d{1,3}$/.test(daysText) ? Number(daysText) : NaN;
  if (!(days >= 0 && days <= MAX_TRIAL_DAYS)) problems.push("SAIPH_TRIAL_DAYS");
  const capText = env.SAIPH_TRIAL_CAP?.trim() ?? "";
  const cap = capText === "" ? null : /^\d{1,9}$/.test(capText) ? Number(capText) : NaN;
  if (cap !== null && !(cap >= 0)) problems.push("SAIPH_TRIAL_CAP");
  const secret = env.SAIPH_TRIAL_SECRET?.trim() ?? "";
  if (days > 0 && !/^[A-Za-z0-9_-]{32,256}$/.test(secret)) problems.push("SAIPH_TRIAL_SECRET");
  if (problems.length || days === 0) return { config: null, problems };
  return { config: { days, cap, secret }, problems };
}

/** @param {Record<string, string | undefined>} env */
export function readTrialConfig(env) {
  return checkTrialConfig(env).config;
}

/**
 * Normalise an address so aliases of one mailbox share one trial: lower case,
 * no "+tag", and for Gmail no dots and one domain.
 * @param {unknown} email
 * @returns {string | null}
 */
export function normaliseEmail(email) {
  if (typeof email !== "string" || email.length > 320) return null;
  const value = email.trim().toLowerCase();
  const at = value.lastIndexOf("@");
  if (at < 1 || at === value.length - 1 || /[\s\u0000-\u001f\u007f]/u.test(value)) return null;
  let local = value.slice(0, at).split("+")[0];
  let domain = value.slice(at + 1);
  if (domain === "googlemail.com") domain = "gmail.com";
  if (domain === "gmail.com") local = local.replaceAll(".", "");
  if (!local || !/^[^@]+$/.test(local) || !/^[a-z0-9.-]+\.[a-z0-9-]+$/.test(domain)) return null;
  return local + "@" + domain;
}

/**
 * Keyed hash of the normalised address, kept in the session and the trial row.
 * The address itself is never stored. Only an email the identity provider says is
 * verified qualifies; anything else yields null (no trial).
 * @param {unknown} claims verified ID token claims
 * @param {TrialConfig | null} config
 * @returns {string | null}
 */
export function trialEmailKey(claims, config) {
  if (!config || !claims || typeof claims !== "object") return null;
  const { email, email_verified: verified } = /** @type {{email?: unknown, email_verified?: unknown}} */ (claims);
  const normalised = verified === true ? normaliseEmail(email) : null;
  if (!normalised) return null;
  return createHmac("sha256", config.secret).update("saiph-trial-email-v1\0" + normalised).digest("hex");
}

/** @param {unknown} value */
export function validEmailKey(value) {
  return typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
}

/** Random grant reference; the Hosted service never learns the subject from it. */
export function newTrialRef() {
  return randomBytes(16).toString("hex");
}

/** @param {string} ref */
export function trialGrant(ref) {
  return "trial:" + ref;
}

/** @typedef {{startedAt: number, endsAt: number}} StoredTrial */
/** @typedef {"off"|"available"|"active"|"ended"|"used"|"full"|"subscribed"|"sign_in_again"} TrialState */

/**
 * What the account page offers. `stored` is this subject's own trial row;
 * `emailUsed` is whether another subject already used this email; `started` is
 * how many trials exist in this database (for the optional cap).
 * @param {{config: TrialConfig | null, stored: StoredTrial | null, emailKey: string | null,
 *   emailUsed: boolean, subscribed: boolean, started: number, now: number}} facts
 * @returns {{state: TrialState, endsAt: number | null, daysLeft: number | null}}
 */
export function trialDecision({ config, stored, emailKey, emailUsed, subscribed, started, now }) {
  if (stored) {
    return now < stored.endsAt
      ? { state: "active", endsAt: stored.endsAt, daysLeft: daysLeft(stored.endsAt, now) }
      : { state: "ended", endsAt: stored.endsAt, daysLeft: 0 };
  }
  const none = { endsAt: null, daysLeft: null };
  if (!config) return { state: "off", ...none };
  // Someone who already subscribed once does not need, and does not get, a trial.
  if (subscribed) return { state: "subscribed", ...none };
  if (!validEmailKey(emailKey)) return { state: "sign_in_again", ...none };
  if (emailUsed) return { state: "used", ...none };
  if (config.cap !== null && started >= config.cap) return { state: "full", ...none };
  return { state: "available", ...none };
}

/** Whole days left, rounded up, so the last day reads "1 day left".
 * @param {number} endsAt @param {number} now */
export function daysLeft(endsAt, now) {
  return Math.max(0, Math.ceil((endsAt - now) / 86400));
}

/** The trial end to carry into a new subscription so the first charge happens
 * when the free trial ends, or null when there is none worth carrying.
 * @param {StoredTrial | null} stored @param {number} now */
export function carriedTrialEnd(stored, now) {
  return stored && stored.endsAt >= now + CARRY_MIN_SECONDS ? stored.endsAt : null;
}

/** Hosted access a trial grants now: its end while running, otherwise nothing.
 * @param {StoredTrial} trial @param {number} now */
export function trialUntil(trial, now) {
  return now < trial.endsAt ? trial.endsAt : 0;
}
