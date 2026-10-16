// SPDX-License-Identifier: AGPL-3.0-or-later
import { test } from "node:test";
import assert from "node:assert/strict";
import { subscriptionSummary } from "../lib/billing/presentation.mjs";

test("stored billing display uses test labels without granting Cloud access", () => {
  const summary = subscriptionSummary({
    status: "active",
    currentPeriodEnd: 1791676800,
    cancelAtPeriodEnd: false,
  });
  assert.equal(summary.label, "Test subscription active");
  assert.equal(summary.period, "Current test period ends 11 Oct 2026 (UTC)");
  assert.deepEqual(Object.keys(summary), ["label", "period"]);
});

test("scheduled cancellation is distinct from terminal subscriptions", () => {
  assert.equal(
    subscriptionSummary({
      status: "active",
      currentPeriodEnd: 1791676800,
      cancelAtPeriodEnd: true,
    }).period,
    "Scheduled to end 11 Oct 2026 (UTC)",
  );
  for (const status of ["canceled", "incomplete_expired"]) {
    assert.equal(
      subscriptionSummary({
        status,
        currentPeriodEnd: 1791676800,
        cancelAtPeriodEnd: true,
      }).period,
      "",
    );
  }
});

test("unknown provider statuses and invalid dates cannot leak payloads or break rendering", () => {
  for (const status of [
    "unrecognized-private-value",
    "constructor",
    "__proto__",
  ]) {
    assert.equal(
      subscriptionSummary({
        status,
        currentPeriodEnd: null,
        cancelAtPeriodEnd: false,
      }).label,
      "Status unavailable",
    );
  }
  for (const currentPeriodEnd of [
    null,
    NaN,
    Infinity,
    -1,
    0,
    253402300800,
    1.5,
  ]) {
    assert.equal(
      subscriptionSummary({
        status: "active",
        currentPeriodEnd,
        cancelAtPeriodEnd: false,
      }).period,
      "",
    );
  }
});
