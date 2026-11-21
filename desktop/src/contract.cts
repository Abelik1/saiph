// SPDX-License-Identifier: AGPL-3.0-or-later
export const PROTOCOL = 1;
export const APP_URL = "saiph-app://desktop/index.html";
export const REQUEST_CHANNEL = "saiph:request";
export const EVENT_CHANNEL = "saiph:event";
export const MAX_REQUEST_BYTES = 64 * 1024;
export const MAX_RESPONSE_BYTES = 32 * 1024 * 1024;
export type Packet = { id: string; ok: boolean; result?: unknown; error?: string; revision?: string; unchanged?: boolean };

export function validateCall(method: unknown, args: unknown): asserts method is string {
  if (typeof method !== "string" || !/^[a-z][a-z0-9_.]{0,79}$/.test(method)
    || !args || typeof args !== "object" || Array.isArray(args)
    || Buffer.byteLength(JSON.stringify(args)) > MAX_REQUEST_BYTES) {
    throw new Error("Invalid desktop request.");
  }
}
