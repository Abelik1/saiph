// SPDX-License-Identifier: AGPL-3.0-or-later
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PhoneCamera } from "./PhoneCamera";
import { CameraSettings } from "./CameraSettings";
import type { CameraStatus, Client, Settings } from "./types";
import { chooseOption } from "../test-helpers";

const ready: CameraStatus = {
  available: true,
  running: false,
  verified: false,
  mode: "windows-obs",
  device_id: null,
  message: "Ready",
};
describe("Phone camera", () => {
  it("starts only on an explicit click and stops the active capture", async () => {
    const call = vi.fn().mockResolvedValue(ready);
    const client = { call } as unknown as Client;
    const view = render(
      <PhoneCamera camera={ready} deviceId="phone" client={client} />,
    );
    expect(call).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", { name: "Use phone as webcam" }),
    );
    await waitFor(() =>
      expect(call).toHaveBeenCalledWith("camera.start", { device_id: "phone" }),
    );
    view.rerender(
      <PhoneCamera
        camera={{ ...ready, running: true, device_id: "phone" }}
        deviceId="other-phone"
        client={client}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Stop phone camera" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("camera.stop"));
  });
  it("does not offer webcam launch for missing platform prerequisites", () => {
    render(
      <PhoneCamera
        camera={{ ...ready, available: false, mode: "unavailable" }}
        deviceId="phone"
        client={{ call: vi.fn() } as unknown as Client}
      />,
    );
    expect(
      screen.getByRole("button", { name: "Use phone as webcam" }),
    ).toBeDisabled();
    expect(
      screen.getByText("Set up the camera once in Settings."),
    ).toBeVisible();
  });
  it("starts the chosen rear camera options only after preference saving succeeds", async () => {
    const call = vi.fn().mockResolvedValue({});
    render(
      <PhoneCamera
        camera={ready}
        deviceId="phone"
        client={{ call } as unknown as Client}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Camera options" }));
    chooseOption("Phone camera", "Rear camera");
    chooseOption("Video quality", "1080p · 30 fps");
    chooseOption("Picture rotation", "90°");
    expect(call).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", { name: "Use phone as webcam" }),
    );
    await waitFor(() =>
      expect(call).toHaveBeenNthCalledWith(2, "camera.start", {
        device_id: "phone",
      }),
    );
    expect(call).toHaveBeenNthCalledWith(1, "settings.save", {
      link: { camera: { facing: "back", quality: "1080p", rotation: "90" } },
    });
  });
  it("keeps setup in Devices and saves camera preferences without starting capture", async () => {
    const call = vi.fn().mockResolvedValue({});
    render(
      <CameraSettings
        settings={{ link: { camera: {} } } as Settings}
        camera={ready}
        client={{ call } as unknown as Client}
      />,
    );
    expect(call).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("Meeting-app configuration", {selector:"summary span"}));
    fireEvent.change(screen.getByLabelText("Linux loopback device"), {
      target: { value: "/dev/video10" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Save camera preferences" }),
    );
    await waitFor(() =>
      expect(call).toHaveBeenCalledWith("settings.save", {
        link: { camera: { v4l2_sink: "/dev/video10" } },
      }),
    );
    fireEvent.click(screen.getByText("Phone camera setup", {selector:"summary span"}));
    fireEvent.click(screen.getByRole("button", { name: "Open camera setup guide" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("camera.help"));
    expect(call).not.toHaveBeenCalledWith("camera.start", expect.anything());
  });
  it("shows setup fields for the actual operating system", () => {
    const props = {
      settings: { link: { camera: {} } } as Settings,
      client: { call: vi.fn() } as unknown as Client,
    };
    const view = render(<CameraSettings {...props} platform="linux" />);
    expect(screen.getByLabelText("Linux loopback device")).not.toBeVisible();
    fireEvent.click(screen.getByText("Meeting-app configuration", {selector:"summary span"}));
    expect(screen.getByLabelText("Linux loopback device")).toBeVisible();
    expect(screen.queryByLabelText("OBS profile")).toBeNull();
    view.rerender(<CameraSettings {...props} platform="windows" />);
    expect(screen.getByLabelText("OBS profile")).toBeVisible();
    expect(screen.queryByLabelText("Linux loopback device")).toBeNull();
  });
});

describe("Phone camera without a self-hosted Hub", () => {
  const phones = [
    { serial: "SYNTHUSB01", state: "ready", model: "Synthetic Phone", connection: "usb" },
    { serial: "192.168.50.20:41234", state: "ready", model: "Wifi Phone", connection: "wifi" },
    { serial: "SYNTHLOCKED", state: "unauthorized", model: "Locked Phone", connection: "usb" },
  ];
  it("finds a phone allowed over USB or Wi-Fi and starts the chosen one by serial", async () => {
    const call = vi.fn(async (method: string) =>
      method === "camera.devices" ? { adb: true, devices: phones } : {},
    );
    render(<PhoneCamera camera={ready} client={{ call } as unknown as Client} />);
    expect(call).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Use phone as webcam" })).toBeDisabled();
    expect(screen.getByText("Find your phone to start the camera.")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Find my phone" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("camera.devices"));
    expect(
      await screen.findByText(
        "Unlock Locked Phone and tap Allow on the debugging prompt, then choose Find again.",
      ),
    ).toBeVisible();
    chooseOption("Phone for the camera", "Wifi Phone · Wi‑Fi");
    fireEvent.click(screen.getByRole("button", { name: "Use phone as webcam" }));
    await waitFor(() =>
      expect(call).toHaveBeenCalledWith("camera.start", { serial: "192.168.50.20:41234" }),
    );
    expect(call).not.toHaveBeenCalledWith(
      "camera.start",
      expect.objectContaining({ device_id: expect.anything() }),
    );
  });
  it("explains a missing adb or an empty list in plain language", async () => {
    const call = vi
      .fn()
      .mockResolvedValueOnce({ adb: false, devices: [] })
      .mockResolvedValueOnce({ adb: true, devices: [] });
    render(<PhoneCamera camera={ready} client={{ call } as unknown as Client} />);
    fireEvent.click(screen.getByRole("button", { name: "Find my phone" }));
    expect(await screen.findByText(/adb was not found\. Install scrcpy/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Find again" }));
    expect(await screen.findByText(/No phone found\. Check the cable/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Use phone as webcam" })).toBeDisabled();
  });
  it("pairs and connects over Wi-Fi, then refreshes the phone list", async () => {
    const call = vi.fn(async (method: string) =>
      method === "camera.devices" ? { adb: true, devices: phones.slice(1, 2) } : {},
    );
    render(<PhoneCamera camera={ready} client={{ call } as unknown as Client} />);
    fireEvent.click(screen.getByText("Connect over Wi‑Fi", { selector: "summary span" }));
    fireEvent.change(screen.getByLabelText("Pairing IP address and port"), {
      target: { value: " 192.168.50.20:37000 " },
    });
    fireEvent.change(screen.getByLabelText("Wi‑Fi pairing code"), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Pair this computer" }));
    await waitFor(() =>
      expect(call).toHaveBeenCalledWith("camera.pair", {
        address: "192.168.50.20:37000",
        code: "123456",
      }),
    );
    expect(await screen.findByText(/^Paired\./)).toBeVisible();
    fireEvent.change(screen.getByLabelText("Phone IP address and port"), {
      target: { value: "192.168.50.20:41234" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Connect over Wi‑Fi" }));
    await waitFor(() =>
      expect(call).toHaveBeenCalledWith("camera.connect", { address: "192.168.50.20:41234" }),
    );
    expect(await screen.findByText("Using Wifi Phone · Wi‑Fi")).toBeVisible();
    expect(call).not.toHaveBeenCalledWith("camera.start", expect.anything());
  });
  it("offers a preview window for OBS setup before the webcam is ready", async () => {
    const call = vi.fn(async (method: string) =>
      method === "camera.devices" ? { adb: true, devices: phones.slice(0, 1) } : {},
    );
    const unready: CameraStatus = { ...ready, available: false, can_preview: true, mode: "unavailable" };
    const view = render(<PhoneCamera camera={unready} client={{ call } as unknown as Client} />);
    expect(screen.getByRole("button", { name: "Open camera preview" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Find my phone" }));
    await screen.findByText("Using Synthetic Phone · USB cable");
    expect(screen.getByRole("button", { name: "Use phone as webcam" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Open camera preview" }));
    await waitFor(() =>
      expect(call).toHaveBeenCalledWith("camera.start", { serial: "SYNTHUSB01", preview: true }),
    );
    view.rerender(
      <PhoneCamera
        camera={{ ...unready, running: true, mode: "preview", serial: "SYNTHUSB01" }}
        client={{ call } as unknown as Client}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Close camera preview" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("camera.stop"));
  });
  it("can open the phone camera directly even when the meeting webcam is already configured", async () => {
    const call = vi.fn().mockResolvedValue({});
    render(<PhoneCamera camera={{...ready, can_preview:true}} deviceId="phone" client={{call} as unknown as Client} />);
    fireEvent.click(screen.getByRole("button", {name:"Open camera preview"}));
    await waitFor(() => expect(call).toHaveBeenCalledWith("camera.start", {device_id:"phone", preview:true}));
  });
  it("explains the one-time phone and OS setup without a Hub", () => {
    const props = {
      settings: { link: { camera: {} } } as Settings,
      client: { call: vi.fn() } as unknown as Client,
    };
    const view = render(<CameraSettings {...props} platform="windows" />);
    expect(
      screen.getByText(/works with Saiph Cloud and without a server or Tailscale/),
    ).toBeInTheDocument();
    expect(screen.getByText(/tap Build number seven times/)).toBeInTheDocument();
    expect(screen.getByText(/Install OBS Studio/)).toBeInTheDocument();
    expect(screen.queryByText(/v4l2loopback-dkms/)).toBeNull();
    view.rerender(<CameraSettings {...props} platform="linux" />);
    expect(screen.getByText(/v4l2loopback-dkms/)).toBeInTheDocument();
    expect(screen.queryByText(/Install OBS Studio/)).toBeNull();
  });
});
