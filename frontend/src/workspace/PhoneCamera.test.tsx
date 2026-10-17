// SPDX-License-Identifier: AGPL-3.0-or-later
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PhoneCamera } from "./PhoneCamera";
import { CameraSettings } from "./CameraSettings";
import type { CameraStatus, Client, Settings } from "./types";

const camera: CameraStatus = { available: false, running: false, verified: false, mode: "unavailable",
  device_id: null, message: "", integrated_available: true, local_state: "idle" };
const code = { session: "a".repeat(32), modules: Array(29).fill("1".repeat(29)), expires_in: 120,
  expires_at: new Date(Date.now() + 120000).toISOString() };

describe("Integrated phone camera", () => {
  it("starts from an explicit action and shows a camera QR without third-party setup", async () => {
    const call = vi.fn().mockResolvedValue(code);
    const { unmount } = render(<PhoneCamera camera={camera} config={{ enabled: false }} client={{ call } as unknown as Client} />);
    expect(call).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Use phone as webcam" }));
    await screen.findByRole("img", { name: "Camera session QR code" });
    expect(call).toHaveBeenNthCalledWith(1, "settings.save", { link: { camera: { enabled: true } } });
    expect(call).toHaveBeenNthCalledWith(2, "camera.session", { preview: false });
    expect(screen.queryByText(/OBS|scrcpy|USB debugging/)).toBeNull();
    unmount();
    expect(call).toHaveBeenLastCalledWith("camera.cancel_invite", { session: code.session });
  });
  it("keeps preview available without registering a virtual camera", async () => {
    const call = vi.fn().mockResolvedValue(code);
    render(<PhoneCamera camera={{ ...camera, integrated_available: false }} client={{ call } as unknown as Client} />);
    expect(screen.getByRole("button", { name: "Use phone as webcam" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Preview camera" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("camera.session", { preview: true }));
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
