// SPDX-License-Identifier: AGPL-3.0-or-later
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import App from "../App";
import { SetupWizard } from "./SetupWizard";
import type { Client, State } from "./types";

const setup = { completed: false, connected: false, show: true, mode: null, platform: "linux",
  tools: { scrcpy: { found: true, purpose: "Phone screen", link: "scrcpy" }, deskflow: { found: false, purpose: "Keyboard and mouse", link: "deskflow" } },
  linux: { xdotool: { found: false, package: "xdotool", purpose: "Remote keys" }, playerctl: { found: true, package: "playerctl", purpose: "Media" },
           bluetoothctl: { found: false, package: "bluez", purpose: "Auto-lock" } } };

function hubState(paired: boolean, phone = false): State {
  return { setup: { ...setup, connected: paired, show: !paired },
    settings: { hub: { paired, base_url: "", device_id: "desktop" }, machine: { name: "Desk", features: {} }, link: {} },
    hosted: { available: true, enabled: false, status: "off", identity: false, configured: true },
    phone: { status: "", error: "", notifications: [], devices: phone ? [{ id: "phone", name: "Galaxy", online: true, last_seen_at: null, capabilities: ["battery"] }] : [] },
  } as unknown as State;
}

describe("Setup guide", () => {
  it("walks through own Hub: connect, phone, features, tools and finish", async () => {
    const call = vi.fn().mockResolvedValue({});
    const close = vi.fn();
    const { rerender } = render(<SetupWizard state={hubState(false)} client={{ call } as unknown as Client} close={close} />);
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /My own Hub/ }));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(screen.getByRole("button", { name: "Open server invitation" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
    rerender(<SetupWizard state={hubState(true, true)} client={{ call } as unknown as Client} close={close} />);
    expect(screen.getByText("This computer is paired with your Hub.")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(screen.getByText("Galaxy is connected.")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByLabelText(/Phone remote/));
    fireEvent.click(screen.getByLabelText(/Copy verification codes automatically/));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("settings.save", { link: {
      clipboard: true, dnd_sync: true, new_photo_notices: true, battery_alerts: true, ring_computer: true, pause_media_on_calls: true,
      auto_copy_codes: true, remote: { enabled: true, devices: ["phone"] }, deskflow: { enabled: false } } }));
    expect(screen.getByLabelText("Install command")).toHaveValue("sudo apt install xdotool bluez");
    expect(screen.queryByText("Deskflow")).toBeNull();  // Only shown when chosen.
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Open Saiph" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("settings.save", { setup: { completed: true } }));
    expect(close).toHaveBeenCalled();
  });

  it("signs in with a Saiph account and keeps the feature list to what Hosted supports", async () => {
    const call = vi.fn().mockResolvedValue({});
    const state = { ...hubState(false), hosted: { available: true, enabled: true, status: "setup", identity: false, configured: true, account: { status: "signed_out", error: "", refresh_tokens: false } } } as unknown as State;
    const { rerender } = render(<SetupWizard state={state} client={{ call } as unknown as Client} close={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /Saiph account/ }));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Sign in with your browser" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("hosted.sign_in"));
    const signedIn = { ...state, hosted: { ...state.hosted!, account: { status: "signed_in", error: "", refresh_tokens: false } } } as State;
    rerender(<SetupWizard state={signedIn} client={{ call } as unknown as Client} close={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Set up this computer" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("hosted.setup_root"));
    rerender(<SetupWizard state={{ ...signedIn, hosted: { ...signedIn.hosted!, identity: true, roster: { expires_at: 1, version: 1, clock_warning: false, members: [] } } } as State} client={{ call } as unknown as Client} close={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(screen.getByLabelText("Phone request code")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Skip for now" }));
    expect(screen.getByLabelText(/Share the clipboard/)).toBeChecked();
    expect(screen.queryByLabelText(/Phone remote/)).toBeNull();
  });

  it("appears on first run, not for computers that are already connected, and can be skipped", async () => {
    const call = vi.fn(async (method: string) => method === "state" ? hubState(false) : {});
    render(<App providedClient={{ call, subscribe: () => () => {} } as unknown as Client} />);
    expect(await screen.findByRole("dialog", { name: "Saiph setup" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Set up later" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("settings.save", { setup: { completed: true } }));
  });
});
