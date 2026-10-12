// SPDX-License-Identifier: AGPL-3.0-or-later
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PairingQr, validQr, type PairingQrCode } from "./PairingQr";

const shownAt = Date.parse("2026-01-01T12:00:00Z");
const qr: PairingQrCode = {
  modules: Array.from({ length: 29 }, (_, y) => "0".repeat(y) + "1" + "0".repeat(28 - y)),
  expires_at: "2026-01-01T12:01:01Z", expires_in: 61,
};
afterEach(() => vi.useRealTimers());

describe("Pairing QR", () => {
  it("rejects malformed grids and invalid or unbounded lifetimes", () => {
    expect(validQr(qr)).toBe(true);
    for (const value of [null, {}, { ...qr, modules: ["1"] },
      { ...qr, modules: qr.modules.map(() => "x".repeat(29)) },
      { ...qr, modules: qr.modules.map(() => "0".repeat(28)) },
      { ...qr, expires_in: 0 }, { ...qr, expires_in: Infinity },
      { ...qr, expires_in: NaN }, { ...qr, expires_in: 3661 },
      { ...qr, expires_at: "invalid" }]) expect(validQr(value)).toBe(false);
  });

  it("renders black modules on a white square with an accessible label and privacy warning", () => {
    vi.useFakeTimers();
    vi.setSystemTime(shownAt);
    const onClose = vi.fn();
    render(<PairingQr qr={qr} shownAt={shownAt} onClose={onClose} onExpire={vi.fn()} />);
    const image = screen.getByRole("img", { name: "Pairing QR code" });
    expect(image).toHaveAttribute("viewBox", "0 0 29 29");
    expect(image.querySelector("rect")).toHaveAttribute("fill", "#fff");
    expect(image.querySelector("path")).toHaveAttribute("fill", "#000");
    expect(screen.getByText(/private invitation/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("uses elapsed wall time, expires at zero, and clears its timer on unmount", () => {
    vi.useFakeTimers();
    vi.setSystemTime(shownAt);
    const onExpire = vi.fn();
    const { unmount } = render(<PairingQr qr={qr} shownAt={shownAt} onClose={vi.fn()} onExpire={onExpire} />);
    expect(screen.getByRole("timer")).toHaveTextContent("Expires in 1:01");
    act(() => vi.advanceTimersByTime(1000));
    expect(screen.getByRole("timer")).toHaveTextContent("Expires in 1:00");
    // A suspended/throttled window must not restart its full invitation lifetime.
    vi.setSystemTime(shownAt + 61000);
    act(() => vi.advanceTimersByTime(1000));
    expect(screen.getByRole("timer")).toHaveTextContent("Expires in 0:00");
    expect(onExpire).toHaveBeenCalledOnce();
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });
});
