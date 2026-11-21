// SPDX-License-Identifier: AGPL-3.0-or-later
import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => { Reflect.deleteProperty(window, "saiphDesktop"); vi.resetModules(); });

describe("Electron transport through the existing desktop client", () => {
  it("retains state revisions, unchanged objects and unsubscribe behaviour", async () => {
    const unsubscribe = vi.fn(), listener = vi.fn();
    const request = vi.fn().mockResolvedValueOnce({ ok: true, revision: "a".repeat(64), result: { phone: { online: true } } })
      .mockResolvedValueOnce({ ok: true, revision: "a".repeat(64), unchanged: true });
    const subscribe = vi.fn(() => unsubscribe);
    Object.assign(window, { saiphDesktop: { version: 1, request, subscribe } });
    const { desktopClient } = await import("./client");
    const client = await desktopClient(), first = await client.call("state");
    expect(await client.call("state")).toBe(first);
    expect(request).toHaveBeenLastCalledWith("state", { revision: "a".repeat(64) });
    client.subscribe(listener)();
    expect(subscribe).toHaveBeenCalledWith(listener);
    expect(unsubscribe).toHaveBeenCalledOnce();
  });
  it("reports unavailable operations and transport failure without fixture fallback", async () => {
    const request = vi.fn().mockResolvedValueOnce({ ok: false, error: "Not migrated yet" }).mockRejectedValueOnce(new Error("Service stopped"));
    Object.assign(window, { saiphDesktop: { version: 1, request, subscribe: vi.fn() } });
    const { desktopClient } = await import("./client");
    const client = await desktopClient();
    await expect(client.call("phone.ring")).rejects.toThrow("Not migrated yet");
    await expect(client.call("state")).rejects.toThrow("Service stopped");
  });
  it("refuses incompatible bridge versions", async () => {
    Object.assign(window, { saiphDesktop: { version: 2 } });
    const { desktopClient } = await import("./client");
    await expect(desktopClient()).rejects.toThrow("version is incompatible");
  });
});
