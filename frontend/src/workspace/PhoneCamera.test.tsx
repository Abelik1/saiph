// SPDX-License-Identifier: AGPL-3.0-or-later
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PhoneCamera } from "./PhoneCamera";
import { CameraSettings } from "./CameraSettings";
import type { CameraStatus, Client, Settings } from "./types";

const camera: CameraStatus = { available: false, running: false, verified: false, mode: "unavailable",
  device_id: null, message: "", integrated_available: true, local_state: "idle" };
const code = { session: "a".repeat(32), modules: Array(29).fill("1".repeat(29)), expires_in: 120,
  expires_at: new Date(Date.now() + 120000).toISOString() };

describe("Integrated phone camera", () => {
  it("applies explicit resolution, frame rate and quality choices only when starting", async () => {
    const call = vi.fn().mockResolvedValue(code);
    render(<PhoneCamera camera={camera} client={{ call } as unknown as Client} />);
    expect(screen.getByRole('button', { name: '1080p' })).toHaveAttribute('aria-pressed', 'true');
    fireEvent.click(screen.getByRole('button', { name: '720p' }));
    fireEvent.click(screen.getByRole('button', { name: '30 fps' }));
    fireEvent.click(screen.getByRole('button', { name: 'Standard' }));
    expect(call).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Preview camera' }));
    await waitFor(() => expect(call).toHaveBeenCalledWith('camera.session', { preview: true, resolution: '720p', fps: 30, quality: 'standard' }));
    expect(screen.queryByRole('button', { name: '1080p' })).toBeNull();
  });
  it("polls at 20 fps without overlapping requests and shows received dimensions and cadence", async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'performance'] });
    try {
      let pending = 0, maximumPending = 0;
      const call = vi.fn(() => new Promise(resolve => {
        maximumPending = Math.max(maximumPending, ++pending);
        setTimeout(() => { pending--; resolve({ image: 'data:image/jpeg;base64,c3ludGhldGlj', sequence: 7, fps: 19.8, source_width: 1920, source_height: 1080 }); }, 20);
      }));
      const { unmount } = render(<PhoneCamera camera={{ ...camera, local_state: 'live', local_resolution: '1080p', local_fps: 20, local_quality: 'high' }} client={{ call } as unknown as Client} />);
      await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
      expect(call.mock.calls.length).toBeGreaterThanOrEqual(20);
      expect(call.mock.calls.length).toBeLessThanOrEqual(21);
      expect(maximumPending).toBe(1);
      expect(screen.getByRole('status')).toHaveTextContent('phone 1920×1080 · receiving 19.8 fps');
      unmount();
    } finally { vi.useRealTimers(); }
  });
  it("includes native response time in the frame period without overlapping slow reads", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "performance"] });
    try {
      let pending = 0;
      let maximumPending = 0;
      const call = vi.fn(() => new Promise((resolve) => {
        pending += 1;
        maximumPending = Math.max(maximumPending, pending);
        setTimeout(() => {
          pending -= 1;
          resolve({ image: "data:image/jpeg;base64,c3ludGhldGlj" });
        }, 40);
      }));
      const { unmount } = render(<PhoneCamera camera={{ ...camera, running: true, local_state: "live" }} client={{ call } as unknown as Client} />);
      await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
      expect(call.mock.calls.length).toBeGreaterThanOrEqual(15);
      expect(call.mock.calls.length).toBeLessThanOrEqual(16);
      expect(maximumPending).toBe(1);
      unmount();
      const calls = call.mock.calls.length;
      await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
      expect(call).toHaveBeenCalledTimes(calls);
    } finally { vi.useRealTimers(); }
  });
  it("refreshes a live preview at camera cadence and stops polling after unmount", async () => {
    vi.useFakeTimers();
    try {
      const call = vi.fn().mockResolvedValue({ image: "data:image/jpeg;base64,c3ludGhldGlj" });
      const { unmount } = render(<PhoneCamera camera={{ ...camera, running: true, local_state: "live" }} client={{ call } as unknown as Client} />);
      await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
      expect(call.mock.calls.filter(([method]) => method === "camera.frame").length).toBeGreaterThanOrEqual(12);
      unmount();
      const calls = call.mock.calls.length;
      await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
      expect(call).toHaveBeenCalledTimes(calls);
    } finally { vi.useRealTimers(); }
  });
  it("waits for a slow frame and does not restart polling after unmount", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "performance"] });
    try {
      let complete: (value: unknown) => void = () => {};
      const call = vi.fn(() => new Promise((resolve) => { complete = resolve; }));
      const { unmount } = render(<PhoneCamera camera={{ ...camera, running: true, local_state: "live" }} client={{ call } as unknown as Client} />);
      await act(async () => { await vi.advanceTimersByTimeAsync(250); });
      expect(call).toHaveBeenCalledTimes(1);
      await act(async () => {
        complete({ image: "data:image/jpeg;base64,c3ludGhldGlj" });
        await vi.advanceTimersByTimeAsync(1);
      });
      expect(call).toHaveBeenCalledTimes(2);
      unmount();
      await act(async () => {
        complete({ image: "data:image/jpeg;base64,c3ludGhldGlj" });
        await vi.advanceTimersByTimeAsync(1000);
      });
      expect(call).toHaveBeenCalledTimes(2);
    } finally { vi.useRealTimers(); }
  });
  it("starts from an explicit action and shows a camera QR without third-party setup", async () => {
    const call = vi.fn().mockResolvedValue(code);
    const { unmount } = render(<PhoneCamera camera={camera} config={{ enabled: false }} client={{ call } as unknown as Client} />);
    expect(call).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Use phone as webcam" }));
    await screen.findByRole("img", { name: "Camera session QR code" });
    expect(call).toHaveBeenNthCalledWith(1, "settings.save", { link: { camera: { enabled: true } } });
    expect(call).toHaveBeenNthCalledWith(2, "camera.session", { preview: false, resolution: "1080p", fps: 20, quality: "high" });
    expect(screen.queryByText(/OBS|scrcpy|USB debugging/)).toBeNull();
    unmount();
    expect(call).toHaveBeenLastCalledWith("camera.cancel_invite", { session: code.session });
  });
  it("keeps preview available without registering a virtual camera", async () => {
    const call = vi.fn().mockResolvedValue(code);
    render(<PhoneCamera camera={{ ...camera, integrated_available: false }} client={{ call } as unknown as Client} />);
    expect(screen.getByRole("button", { name: "Use phone as webcam" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Preview camera" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("camera.session", { preview: true, resolution: "1080p", fps: 20, quality: "high" }));
  });
  it("clears a consumed code after the native session ends", async () => {
    const call = vi.fn().mockResolvedValue(code);
    const { rerender } = render(<PhoneCamera camera={camera} client={{ call } as unknown as Client} />);
    fireEvent.click(screen.getByRole("button", { name: "Use phone as webcam" }));
    await screen.findByRole("img", { name: "Camera session QR code" });
    rerender(<PhoneCamera camera={{ ...camera, local_state: "waiting" }} client={{ call } as unknown as Client} />);
    rerender(<PhoneCamera camera={{ ...camera, local_state: "idle", local_message: "Camera disconnected." }} client={{ call } as unknown as Client} />);
    expect(screen.queryByRole("img", { name: "Camera session QR code" })).toBeNull();
    expect(screen.getByText("Camera disconnected.")).toBeVisible();
  });
  it("still offers Stop for a legacy capture session", async () => {
    const call = vi.fn().mockResolvedValue({});
    render(<PhoneCamera camera={{ ...camera, running: true, mode: "preview" }} client={{ call } as unknown as Client} />);
    fireEvent.click(screen.getByRole("button", { name: "Stop camera" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("camera.stop"));
    expect(call).not.toHaveBeenCalledWith("camera.session", expect.anything());
  });
  it("shows the native live preview and stops explicitly", async () => {
    const call = vi.fn().mockResolvedValue({ image: "data:image/jpeg;base64,c3ludGhldGlj" });
    render(<PhoneCamera camera={{ ...camera, running: true, local_state: "live" }} client={{ call } as unknown as Client} />);
    await screen.findByAltText("Live phone camera preview");
    fireEvent.click(screen.getByRole("button", { name: "Stop camera" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("camera.stop"));
  });
  it("sends the code to a linked Cloud phone and keeps the QR as a fallback", async () => {
    const call = vi.fn((method: string) => Promise.resolve(method === "camera.offer" ? { sent: true, name: "Pixel" } : code));
    render(<PhoneCamera camera={camera} cloudPhone={{ id: "dev_" + "1".repeat(32), name: "Pixel" }} client={{ call } as unknown as Client} />);
    fireEvent.click(screen.getByRole("button", { name: "Use phone as webcam" }));
    expect(await screen.findByText(/Sent to Pixel/)).toBeVisible();
    expect(call).toHaveBeenCalledWith("camera.offer", { session: code.session, device_id: "dev_" + "1".repeat(32) });
    expect(screen.getByRole("img", { name: "Camera session QR code" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Send to Pixel again" }));
    await waitFor(() => expect(call.mock.calls.filter(([method]) => method === "camera.offer")).toHaveLength(2));
  });
  it("falls back to scanning when the Cloud request cannot be sent", async () => {
    const call = vi.fn((method: string) => method === "camera.offer" ? Promise.reject(new Error("Pixel is offline. Scan the code instead.")) : Promise.resolve(code));
    render(<PhoneCamera camera={camera} cloudPhone={{ id: "dev_" + "1".repeat(32), name: "Pixel" }} client={{ call } as unknown as Client} />);
    fireEvent.click(screen.getByRole("button", { name: "Use phone as webcam" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Pixel is offline. Scan the code instead.");
    expect(screen.getByRole("img", { name: "Camera session QR code" })).toBeVisible();
  });
  it("never sends a camera request without a linked Cloud phone", async () => {
    const call = vi.fn().mockResolvedValue(code);
    render(<PhoneCamera camera={camera} client={{ call } as unknown as Client} />);
    fireEvent.click(screen.getByRole("button", { name: "Use phone as webcam" }));
    await screen.findByRole("img", { name: "Camera session QR code" });
    expect(call).not.toHaveBeenCalledWith("camera.offer", expect.anything());
  });
  it("saves preferences without starting capture and keeps tool instructions collapsed", async () => {
    const call = vi.fn().mockResolvedValue({});
    render(<CameraSettings settings={{ link: { camera: { enabled: false } } } as Settings} client={{ call } as unknown as Client} platform="windows" />);
    expect(screen.queryByRole("button", { name: "Download OBS Studio" })).toBeNull();
    fireEvent.click(screen.getByRole("switch", { name: "Allow phone camera" }));
    fireEvent.click(screen.getByRole("button", { name: "Save camera preferences" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("settings.save", { link: { camera: { enabled: true } } }));
    expect(call).not.toHaveBeenCalledWith("camera.session", expect.anything());
  });
});
