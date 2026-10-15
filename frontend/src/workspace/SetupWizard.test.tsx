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
    // A Saiph account is preselected; self-hosting is an explicit choice.
    expect(screen.getByRole("button", { name: /Saiph account/ })).toHaveClass("selected");
    fireEvent.click(screen.getByRole("button", { name: /self-host my own Hub/ }));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByRole("button", { name: "Open server invitation" })).toBeVisible();
    expect(call).toHaveBeenCalledWith("settings.save", { setup: { mode: "hub" } });
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
    fireEvent.click(screen.getByRole("button", { name: "Sign in to Saiph" }));
    expect(call).toHaveBeenCalledWith("settings.save", { setup: { mode: "hosted" } });
    await waitFor(() => expect(call).toHaveBeenCalledWith("hosted.sign_in"));
    const signedIn = { ...state, hosted: { ...state.hosted!, account: { status: "signed_in", error: "", refresh_tokens: false } } } as State;
    rerender(<SetupWizard state={signedIn} client={{ call } as unknown as Client} close={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Set up this computer" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("hosted.setup_root"));
    rerender(<SetupWizard state={{ ...signedIn, hosted: { ...signedIn.hosted!, identity: true, roster: { expires_at: 1, version: 1, clock_warning: false, members: [] } } } as State} client={{ call } as unknown as Client} close={vi.fn()} />);
    // Setting up moves straight on to the phone and shows this computer's code without another click.
    expect(await screen.findByText("Add your Android phone")).toBeVisible();
    await waitFor(() => expect(call).toHaveBeenCalledWith("hosted.root_code"));
    fireEvent.click(screen.getByRole("button", { name: "Continue to approval" }));
    expect(screen.getByText(/Waiting for your device/)).toBeVisible();  // Offered requests appear by themselves.
    expect(screen.getByText("My device hasn't appeared")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Skip for now" }));
    expect(screen.getByLabelText(/Share the clipboard/)).toBeChecked();
    expect(screen.queryByLabelText(/Phone remote/)).toBeNull();
  });

  it("starts from a fresh bundled account with one sign-in action and no deployment form", async () => {
    const call = vi.fn().mockResolvedValue({});
    render(<SetupWizard state={hubState(false)} client={{ call } as unknown as Client} close={vi.fn()} />);
    expect(call).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Sign in to Saiph" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("hosted.sign_in"));
    expect(call.mock.calls.map(([method]) => method)).toEqual(["settings.save", "hosted.enable", "hosted.sign_in"]);
    expect(screen.queryByText(/Enter them under Settings/)).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(call).not.toHaveBeenCalledWith("hosted.setup_root");
  });

  it("reports a failed enable without opening the browser or losing the retry action", async () => {
    const call = vi.fn(async (method: string) => {
      if (method === "hosted.enable") throw new Error("Connection could not be started.");
      return {};
    });
    render(<SetupWizard state={hubState(false)} client={{ call } as unknown as Client} close={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Sign in to Saiph" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Connection could not be started.");
    expect(call).not.toHaveBeenCalledWith("hosted.sign_in");
    expect(screen.getByRole("button", { name: "Sign in to Saiph" })).toBeEnabled();
  });

  it("does not ask people to supply service settings when a build is incomplete", () => {
    const state = hubState(false);
    state.hosted!.configured = false;
    const call = vi.fn();
    render(<SetupWizard state={state} client={{ call } as unknown as Client} close={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Sign in to Saiph" })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("Download the current beta");
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(call).not.toHaveBeenCalled();
  });

  it("lets a second computer join as another computer and waits for its main computer", async () => {
    const call = vi.fn().mockResolvedValue({});
    const account = { status: "signed_in", error: "", refresh_tokens: false };
    const fresh = { ...hubState(false), hosted: { available: true, enabled: true, status: "setup", identity: false, configured: true, account } } as unknown as State;
    const { rerender } = render(<SetupWizard state={fresh} client={{ call } as unknown as Client} close={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByText("Already use Saiph Hosted on another computer?")).toBeInTheDocument();
    expect(screen.getByLabelText("Main computer's code")).toBeInTheDocument();
    const waiting = { ...fresh, hosted: { ...fresh.hosted!, identity: true, role: "member", status: "awaiting_approval" } } as State;
    rerender(<SetupWizard state={waiting} client={{ call } as unknown as Client} close={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Show request code" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
    const approved = { ...waiting, hosted: { ...waiting.hosted!, status: "active", roster: { expires_at: 1, version: 2, clock_warning: false, members: [
      { id: "dev_main", label: "Main computer", root: true, self: false, fingerprint: "A" }, { id: "dev_self", label: "This computer", root: false, self: true, fingerprint: "B" }] } } } as State;
    rerender(<SetupWizard state={approved} client={{ call } as unknown as Client} close={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(screen.getByText(/Phones are added on your main computer/)).toBeVisible();
    expect(screen.queryByLabelText("Device request code")).toBeNull();
    expect(screen.getByRole("button", { name: "Skip for now" })).toBeVisible();
  });
  it("starts a connected computer at the feature choices", () => {
    const call = vi.fn().mockResolvedValue({});
    render(<SetupWizard state={{ ...hubState(true, true), setup: { ...setup, mode: "hub", connected: true, show: false } } as State} client={{ call } as unknown as Client} close={vi.fn()} />);
    expect(screen.getByRole("heading", { name: "Choose features" })).toBeVisible();
    expect(screen.queryByText("How do you want to connect your devices?")).toBeNull();
    expect(screen.getByLabelText(/Share the clipboard/)).toBeChecked();
  });
  it("opens first connection in Phone and keeps the optional guide reachable from Settings", async () => {
    const call = vi.fn(async (method: string) => method === "state" ? hubState(false) : {});
    render(<App providedClient={{ call, subscribe: () => () => {} } as unknown as Client} />);
    expect(await screen.findByRole("heading", { name: "Connect your phone" })).toBeVisible();
    expect(screen.queryByRole("dialog", { name: "Saiph setup" })).toBeNull();
    expect(screen.getByRole("button", { name: "Sign in to Saiph" })).toBeEnabled();
    expect(call.mock.calls.map(([method]) => method)).toEqual(["state"]);
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    fireEvent.click(screen.getByRole("button", { name: "Run the setup guide" }));
    expect(screen.getByRole("dialog", { name: "Saiph setup" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Set up later" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("settings.save", { setup: { completed: true } }));
  });
});
