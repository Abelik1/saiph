// SPDX-License-Identifier: AGPL-3.0-or-later
// Onboarding preview: a fresh install signing in to a simulated Saiph account, for
// `npm run dev` only. Open /onboarding.html. Not part of the production build.
// The browser sign-in and the phone are simulated; every value is made up.
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "../index.css";
import App from "../App.tsx";
import type { Client, State } from "../workspace/types";
import { fixtureState } from "./fixture";

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
// A valid-looking QR grid; the preview never encodes a real code.
const modules = Array.from({ length: 33 }, (_, y) => Array.from({ length: 33 }, (_, x) => ((x * 7 + y * 13 + x * y) % 5 < 2 ? "1" : "0")).join(""));

function onboardingClient(): Client {
  const base = fixtureState();
  const state = {
    ...base,
    settings: { ...base.settings, hub: { base_url: "", device_id: "", paired: false } },
    setup: { completed: false, connected: false, show: true, mode: null, platform: "windows", tools: {}, linux: {} },
    phone: { status: "", error: "", devices: [], notifications: [] },
    hosted: { available: true, enabled: false, status: "off", identity: false, configured: true,
      account: { status: "signed_out", error: "", refresh_tokens: false }, roster: null, user_verification: "windows_hello" },
  } as unknown as State;
  const hosted = () => state.hosted!;
  const root = { id: "root", label: "This computer", root: true, self: true, fingerprint: "7C1E 0A42 9D3B 55F0 E218 6B7A 1023 4567 89AB CDEF 0123 4567 89AB CDEF 0123 4567" };
  let rootShown = 0;
  let approved = false;
  // The desktop bridge signals every change; App refreshes its state on that signal.
  const listeners = new Set<() => void>();
  const changed = () => listeners.forEach((fn) => fn());
  return {
    async call<T>(method: string, args?: Record<string, unknown>): Promise<T> {
      if (method === "state") return { ...state, hosted: { ...hosted() } } as T;
      await wait(400);
      if (method === "hosted.enable") Object.assign(hosted(), { enabled: args?.enabled === true, status: args?.enabled ? "setup" : "off" });
      if (method === "hosted.sign_in") {
        hosted().account = { status: "signing_in", error: "", refresh_tokens: false };
        void wait(2500).then(() => { hosted().account = { status: "signed_in", error: "", refresh_tokens: false }; changed(); });
      }
      if (method === "hosted.setup_root" || method === "hosted.root_code") {
        Object.assign(hosted(), { identity: true, role: "root", status: "active", roster: { expires_at: 1_900_000_000, version: 1, clock_warning: false, members: approved ? [root, phone] : [root] } });
        state.setup = { ...state.setup!, connected: true };
        rootShown = Date.now();
        void wait(0).then(changed);
        return { code: "orion-root-v1:preview", fingerprint: root.fingerprint, modules, expires_at: new Date(Date.now() + 300_000).toISOString(), expires_in: 300 } as T;
      }
      if (method === "hosted.requests")
        return { requests: rootShown && !approved && Date.now() - rootShown > 4000 ? [offered] : [] } as T;
      void wait(0).then(changed);
      if (method === "hosted.approve") {
        approved = true;
        hosted().roster = { ...hosted().roster!, version: 2, members: [root, { ...phone, label: String(args?.label || "Phone") }] };
        state.phone = { status: "Connected", error: "", notifications: [], devices: [{
          id: phone.id, name: String(args?.label || "Phone"), online: true, hosted: true,
          last_seen_at: null, capabilities: ["files", "notifications"],
        }] };
      }
      return { ok: true } as T;
    },
    subscribe(fn) { listeners.add(fn); return () => { listeners.delete(fn); }; },
  };
}
const phone = { id: "dev_phone", label: "Phone", root: false, fingerprint: "3F9A 1C07 B2E4 6D18 90AF 52C3 0123 4567 89AB CDEF 0123 4567 89AB CDEF 0123 4567" };
const offered = { code: "orion-approve-v1:preview", device_id: phone.id, fingerprint: phone.fingerprint, expires_at: 1_900_000_000 };

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App providedClient={onboardingClient()} />
  </StrictMode>,
);
