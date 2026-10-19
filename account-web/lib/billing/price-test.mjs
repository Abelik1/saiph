// SPDX-License-Identifier: AGPL-3.0-or-later
// Optional price test (docs/LANDING_CONVERSION.md, website/ANALYTICS.md). Off
// unless SAIPH_PRICE_TEST is set. The website assigns a visitor a variant once
// and shows its prices; this file maps the variant to Stripe price IDs. Variant
// "a" is always the standard price (STRIPE_PRICE_ID / STRIPE_YEARLY_PRICE_ID).
//
// SAIPH_PRICE_TEST='{"id":"2026-11-price","variants":{"b":{
//   "monthly":{"price":"price_...","amount":799},"yearly":{"price":"price_...","amount":6999}}}}'
//
// Keep a test's prices here for as long as any subscription uses them: the
// webhook only accepts subscriptions on configured prices.

/** @typedef {"monthly"|"yearly"} PlanKey */
/** @typedef {{priceId: string, amount: number}} VariantPrice */
/** @typedef {{id: string, variants: Record<string, Record<PlanKey, VariantPrice>>}} PriceTest */

const TEST_ID = /^[a-z0-9][a-z0-9-]{0,39}$/;
const VARIANT = /^[b-d]$/;
const PRICE_ID = /^price_[A-Za-z0-9]+$/;

/**
 * @param {Record<string, string | undefined>} env
 * @param {string[]} standardPrices the configured monthly and yearly price IDs
 * @returns {{test: PriceTest | null, problems: string[]}}
 */
export function checkPriceTest(env, standardPrices = []) {
  const text = env.SAIPH_PRICE_TEST?.trim() ?? "";
  if (!text) return { test: null, problems: [] };
  const fail = { test: null, problems: ["SAIPH_PRICE_TEST"] };
  let value;
  try { value = JSON.parse(text); } catch { return fail; }
  if (!value || typeof value !== "object" || Array.isArray(value) || Object.keys(value).sort().join() !== "id,variants"
      || typeof value.id !== "string" || !TEST_ID.test(value.id)
      || !value.variants || typeof value.variants !== "object" || Array.isArray(value.variants)) return fail;
  const keys = Object.keys(value.variants);
  if (!keys.length || keys.some((key) => !VARIANT.test(key))) return fail;
  const seen = new Set(standardPrices);
  /** @type {PriceTest["variants"]} */
  const variants = {};
  for (const key of keys) {
    const entry = value.variants[key];
    if (!entry || typeof entry !== "object" || Object.keys(entry).sort().join() !== "monthly,yearly") return fail;
    /** @type {Record<string, VariantPrice>} */
    const plans = {};
    for (const plan of /** @type {PlanKey[]} */ (["monthly", "yearly"])) {
      const price = entry[plan];
      if (!price || typeof price !== "object" || Object.keys(price).sort().join() !== "amount,price"
          || typeof price.price !== "string" || !PRICE_ID.test(price.price) || seen.has(price.price)
          || !Number.isInteger(price.amount) || price.amount < 100 || price.amount > 99999) return fail;
      seen.add(price.price);
      plans[plan] = { priceId: price.price, amount: price.amount };
    }
    variants[key] = /** @type {Record<PlanKey, VariantPrice>} */ (plans);
  }
  return { test: { id: value.id, variants }, problems: [] };
}

/**
 * The variant to charge for a requested offer: one the test defines, else the
 * standard price "a". The page and the checkout both use this, so the price shown
 * before sign-in is the one Stripe charges.
 * @param {PriceTest | null} test @param {unknown} offer
 * @returns {{test: string | null, variant: string}}
 */
export function resolveOffer(test, offer) {
  if (!test) return { test: null, variant: "a" };
  if (typeof offer === "string" && Object.hasOwn(test.variants, offer)) return { test: test.id, variant: offer };
  // "a" from a test participant: the standard price, still counted in the test.
  return { test: offer === "a" ? test.id : null, variant: "a" };
}

/** @param {number} cents */
export function euros(cents) {
  return "€" + (cents / 100).toFixed(2);
}
