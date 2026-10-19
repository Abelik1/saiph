// SPDX-License-Identifier: AGPL-3.0-or-later
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { NearbyPhone } from "./NearbyPhone";
import type { Client } from "./types";

function client(status: () => unknown, extra: Record<string, unknown> = {}) {
  return vi.fn((method: string) => {
    if (method === "hosted.link.start") return Promise.resolve({ listening: true, expires_in: 300, peer: null, error: "" });
    if (method === "hosted.link.status") return Promise.resolve(status());
    if (method in extra) return Promise.resolve(extra[method]);
    return Promise.resolve({});
  });
}

describe("Connect a nearby phone without a QR code", () => {
  it("listens only while shown and stops when closed", async () => {
    const call = client(() => ({ listening: true, peer: null }));
    const { unmount } = render(<NearbyPhone client={{ call } as unknown as Client} />);
    expect(await screen.findByText(/tap Find my computer/)).toBeVisible();
    expect(call).toHaveBeenCalledWith("hosted.link.start");
    unmount();
    expect(call).toHaveBeenLastCalledWith("hosted.link.stop");
  });
  it("shows the comparison code and approves only after the phone confirmed", async () => {
    let peer: unknown = { name: "Pixel", code: "713 284", state: "comparing" };
    const onActive = vi.fn(), onApproved = vi.fn();
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    try {
      const call = client(() => ({ listening: true, peer }), { "hosted.link.approve": { approved: "dev_1", label: "Pixel" } });
      render(<NearbyPhone client={{ call } as unknown as Client} onActive={onActive} onApproved={onApproved} />);
      expect(await screen.findByLabelText("Comparison code 713 284")).toBeVisible();
      expect(onActive).toHaveBeenLastCalledWith(true);
      expect(screen.queryByRole("button", { name: "Codes match, approve" })).toBeNull();
      peer = { name: "Pixel", code: "713 284", state: "requested" };
      await act(async () => { vi.advanceTimersByTime(1500); });
      fireEvent.click(await screen.findByRole("button", { name: "Codes match, approve" }));
      await waitFor(() => expect(onApproved).toHaveBeenCalledWith("Pixel"));
      expect(call).toHaveBeenCalledWith("hosted.link.approve", { code: "713 284", confirmed: true });
    } finally { vi.useRealTimers(); }
  });
  it("ignores a malformed peer and explains when listening is unavailable", async () => {
    const call = client(() => ({ listening: true, peer: { name: "Pixel", code: "<b>1</b>", state: "requested" } }));
    render(<NearbyPhone client={{ call } as unknown as Client} />);
    expect(await screen.findByText(/tap Find my computer/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Codes match, approve" })).toBeNull();
    const failing = vi.fn((method: string) => method === "hosted.link.start"
      ? Promise.reject(new Error("Another Saiph window is already looking for phones on this network. Scan the code instead.")) : Promise.resolve({}));
    render(<NearbyPhone client={{ call: failing } as unknown as Client} />);
    expect(await screen.findByText(/already looking for phones/)).toBeVisible();
  });
});
