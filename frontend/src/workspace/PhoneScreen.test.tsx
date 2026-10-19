// SPDX-License-Identifier: AGPL-3.0-or-later
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PhoneScreen, framePoint, gesture, typed } from "./PhoneScreen";
import type { Client, PhoneScreenStatus } from "./types";

const idle: PhoneScreenStatus = { state: "idle", running: false, waiting: false, message: "", resolution: "1080p", fps: 20,
  quality: "high", input: false, delivered: false, device_id: null, launch: "" };
const code = (delivered: boolean) => ({ session: "a".repeat(32), modules: Array(29).fill("1".repeat(29)), expires_in: 120,
  expires_at: new Date(Date.now() + 120000).toISOString(), delivered });
const frame = { image: "data:image/jpeg;base64,c3ludGhldGlj", sequence: 3, fps: 19.6, width: 540, height: 1170 };

describe("Phone screen geometry", () => {
  it("maps pointer positions inside the contained frame and ignores letterboxing", () => {
    // A 540×1170 portrait frame centred in a 1000×1170 box: 230 px bars left and right.
    const box = { left: 0, top: 0, width: 1000, height: 1170 };
    expect(framePoint(box, { width: 540, height: 1170 }, 230, 0)).toEqual({ x: 0, y: 0 });
    expect(framePoint(box, { width: 540, height: 1170 }, 500, 585)).toEqual({ x: 5000, y: 5000 });
    expect(framePoint(box, { width: 540, height: 1170 }, 100, 585)).toBeNull();
    expect(framePoint(box, { width: 0, height: 0 }, 500, 585)).toBeNull();
  });
  it("turns presses into taps, long presses and bounded swipes", () => {
    expect(gesture({ x: 10, y: 10, at: 0 }, { x: 20, y: 30, at: 100 })).toEqual({ t: "tap", x: 10, y: 10 });
    expect(gesture({ x: 10, y: 10, at: 0 }, { x: 10, y: 10, at: 700 })).toEqual({ t: "long", x: 10, y: 10 });
    expect(gesture({ x: 5000, y: 8000, at: 0 }, { x: 5000, y: 2000, at: 10 })).toEqual({ t: "swipe", x: 5000, y: 8000, x2: 5000, y2: 2000, ms: 50 });
    expect(gesture({ x: 0, y: 0, at: 0 }, { x: 9000, y: 0, at: 9000 })).toMatchObject({ ms: 3000 });
  });
  it("keeps typed text printable and short", () => {
    expect(typed("a\u0000b\nc")).toBe("abc");
    expect(Array.from(typed("😀".repeat(300)))).toHaveLength(256);
  });
});

describe("Phone screen session", () => {
  it("in the desktop app, a live session shows in its own window with a red Live badge", async () => {
    vi.useFakeTimers();
    try {
      const call = vi.fn(async (_method: string) => ({ shown: true }));
      render(<PhoneScreen screen={{ ...idle, state: "live", running: true, input: true, window: "open" }} client={{ call } as unknown as Client} />);
      expect(screen.getByRole("status", { name: "Your phone screen is live on this computer" })).toHaveTextContent("Live");
      expect(screen.getByText(/Showing in its own window/)).toBeVisible();
      expect(screen.queryByRole("img", { name: "Your phone's screen" })).toBeNull();
      await act(async () => { await vi.advanceTimersByTimeAsync(500); });
      // The page does not poll frames while the native window shows them.
      expect(call.mock.calls.some(([method]) => method === "screen.frame")).toBe(false);
      fireEvent.click(screen.getByRole("button", { name: "Show window" }));
      await act(async () => { await vi.advanceTimersByTimeAsync(0); });
      expect(call).toHaveBeenCalledWith("screen.window");
      expect(screen.getByRole("button", { name: "Stop" })).toBeVisible();
    } finally { vi.useRealTimers(); }
  });
  it("shows the code for a session started from Mirror screen", async () => {
    const call = vi.fn(async (method: string) => method === "screen.invite" ? code(false) : {});
    render(<PhoneScreen screen={{ ...idle, state: "waiting", waiting: true, window: "closed" }} deviceId="phone" client={{ call } as unknown as Client} />);
    expect(await screen.findByRole("img", { name: "Phone screen QR code" })).toBeVisible();
    expect(call).toHaveBeenCalledWith("screen.invite");
  });
  it("tells the owner it opens in its own window when the desktop app has one", () => {
    render(<PhoneScreen screen={{ ...idle, window: "closed" }} client={{ call: vi.fn() } as unknown as Client} />);
    expect(screen.getByText(/See and use your phone in its own window/)).toBeVisible();
  });
  it("starts with the chosen profile, explains the Cloud notification and keeps a QR fallback", async () => {
    const call = vi.fn().mockResolvedValue(code(true));
    render(<PhoneScreen screen={idle} deviceId="phone" client={{ call } as unknown as Client} />);
    fireEvent.click(screen.getByRole("button", { name: "720p" }));
    fireEvent.click(screen.getByRole("button", { name: "30 fps" }));
    fireEvent.click(screen.getByRole("button", { name: "Show phone screen" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("screen.session", { device_id: "phone", resolution: "720p", fps: 30, quality: "high" }));
    expect(await screen.findByText(/tap the Saiph notification/)).toBeVisible();
    expect(screen.queryByRole("img", { name: "Phone screen QR code" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Show a code to scan/ }));
    expect(screen.getByRole("img", { name: "Phone screen QR code" })).toBeVisible();
  });
  it("shows the QR straight away when the offer could not be delivered", async () => {
    const call = vi.fn().mockResolvedValue(code(false));
    render(<PhoneScreen screen={idle} client={{ call } as unknown as Client} />);
    fireEvent.click(screen.getByRole("button", { name: "Show phone screen" }));
    expect(await screen.findByRole("img", { name: "Phone screen QR code" })).toBeVisible();
    expect(call).toHaveBeenCalledWith("screen.session", { resolution: "1080p", fps: 20, quality: "high" });
  });
  it("is view only until the phone allows input", async () => {
    const call = vi.fn(async (method: string) => method === "screen.frame" ? frame : { sent: true });
    render(<PhoneScreen screen={{ ...idle, state: "live", running: true, input: false }} client={{ call } as unknown as Client} />);
    const view = await screen.findByRole("img", { name: "Your phone's screen" });
    expect(screen.getByText(/View only/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Back" })).toBeDisabled();
    fireEvent.keyDown(view, { key: "Escape" });
    fireEvent.pointerDown(view, { clientX: 10, clientY: 10, pointerId: 1 });
    fireEvent.pointerUp(view, { clientX: 10, clientY: 10, pointerId: 1 });
    expect(call.mock.calls.some(([method]) => method === "screen.input")).toBe(false);
  });
  it("sends taps, keys and typed text while live with input on", async () => {
    vi.spyOn(HTMLImageElement.prototype, "getBoundingClientRect").mockReturnValue({ left: 0, top: 0, width: 540, height: 1170, right: 540, bottom: 1170, x: 0, y: 0, toJSON: () => ({}) });
    const call = vi.fn(async (method: string) => method === "screen.frame" ? frame : { sent: true });
    render(<PhoneScreen screen={{ ...idle, state: "live", running: true, input: true }} client={{ call } as unknown as Client} />);
    const view = await screen.findByRole("img", { name: "Your phone's screen" });
    fireEvent.pointerDown(view, { clientX: 270, clientY: 585, pointerId: 1 });
    fireEvent.pointerUp(view, { clientX: 270, clientY: 585, pointerId: 1 });
    await waitFor(() => expect(call).toHaveBeenCalledWith("screen.input", { event: { t: "tap", x: 5000, y: 5000 } }));
    fireEvent.keyDown(view, { key: "Escape" });
    await waitFor(() => expect(call).toHaveBeenCalledWith("screen.input", { event: { t: "key", key: "back" } }));
    fireEvent.click(screen.getByRole("button", { name: "Home" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("screen.input", { event: { t: "key", key: "home" } }));
    fireEvent.keyDown(view, { key: "h" }); fireEvent.keyDown(view, { key: "i" });
    await waitFor(() => expect(call).toHaveBeenCalledWith("screen.input", { event: { t: "text", text: "hi" } }));
    expect(screen.getByText(/540×1170 · receiving 19.6 fps/)).toBeVisible();
    vi.restoreAllMocks();
  });
  it("stops the session", async () => {
    const call = vi.fn(async (method: string) => method === "screen.frame" ? frame : { stopped: true });
    render(<PhoneScreen screen={{ ...idle, state: "live", running: true }} client={{ call } as unknown as Client} />);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Stop" })); });
    await waitFor(() => expect(call).toHaveBeenCalledWith("screen.stop"));
  });
});
