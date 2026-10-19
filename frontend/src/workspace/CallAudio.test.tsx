// SPDX-License-Identifier: AGPL-3.0-or-later
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CallAudioSession, CallAudioSetup, callAudioOn } from "./CallAudio";
import { PhoneTabs, type PhoneFeatureState } from "./PhoneTabs";
import { chooseOption, openTab } from "../test-helpers";
import type { CallAudioStatus, Client } from "./types";

const PHONE = "AA:BB:CC:DD:EE:01";
const ready: CallAudioStatus = {
  supported: true, platform: "linux", windows: false, enabled: true, device: PHONE, readiness: "ready",
  message: "Calls you answer here use this computer's microphone and speakers.", checking: false,
  devices: [{ address: PHONE, name: "Test Phone", paired: true, connected: true, gateway: true }], phone_connected: true,
  versions: { pipewire: "1.6.2", wireplumber: "0.5.13", bluez: "5.85" }, call_control: "hfp", issues: [],
  setup: { action: "", file: "", applied: false }, session: { state: "idle", message: "", codec: "" }, error: "",
};
const client = (call = vi.fn().mockResolvedValue({})) => ({ client: { call } as unknown as Client, call });

describe("Talk through this computer", () => {
  it("is on only when enabled and ready", () => {
    expect(callAudioOn(ready)).toBe(true);
    expect(callAudioOn({ ...ready, enabled: false })).toBe(false);
    expect(callAudioOn({ ...ready, readiness: "phone-away" })).toBe(false);
    expect(callAudioOn(undefined)).toBe(false);
  });

  it("chooses the paired phone and turns call audio on", async () => {
    const { client: c, call } = client();
    render(<CallAudioSetup status={{ ...ready, enabled: false, device: "", readiness: "choose-phone", message: "Choose the phone you paired with this computer." }} client={c} />);
    expect(screen.getByRole("switch", { name: "Use this computer for call audio" })).toBeDisabled();
    expect(screen.getByText(/never through Saiph Cloud or your server/)).toBeVisible();
    chooseOption("Phone", "Test Phone");
    await waitFor(() => expect(call).toHaveBeenCalledWith("settings.save", { link: { call_audio: { enabled: false, device: PHONE } } }));
    fireEvent.click(screen.getByRole("switch", { name: "Use this computer for call audio" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("settings.save", { link: { call_audio: { enabled: true, device: PHONE } } }));
  });

  it("asks before writing the per-user WirePlumber file", async () => {
    const { client: c, call } = client();
    render(<CallAudioSetup status={{ ...ready, readiness: "needs-setup", message: "Not set up.", setup: { action: "write", file: "~/.config/wireplumber/bluetooth.lua.d/51-saiph-hfp-hf.lua", applied: false } }} client={c} />);
    expect(screen.getByText(/restarts WirePlumber/)).toBeVisible();
    expect(screen.queryByLabelText("Phone")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Turn on hands-free" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("call_audio.setup", {}));
  });

  it("explains Windows honestly and shows nothing elsewhere", () => {
    const { client: c } = client();
    const { container, rerender } = render(<CallAudioSetup status={{ ...ready, supported: false, windows: true }} client={c} />);
    expect(screen.getByText(/Windows keeps for Phone Link/)).toBeVisible();
    rerender(<CallAudioSetup status={{ ...ready, supported: false, windows: false, platform: "darwin" }} client={c} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("says where the call audio is and offers to bring it here", async () => {
    const { client: c, call } = client();
    const { rerender } = render(<CallAudioSession status={{ ...ready, session: { state: "here", message: "", codec: "mSBC" } }} live client={c} />);
    expect(screen.getByRole("status")).toHaveTextContent("Talking through this computer · mSBC");
    rerender(<CallAudioSession status={{ ...ready, session: { state: "on-phone", message: "The call is on your phone.", codec: "" } }} live client={c} />);
    fireEvent.click(screen.getByRole("button", { name: "Move audio here" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("call_audio.move_here", {}));
    rerender(<CallAudioSession status={{ ...ready, call_control: "app", session: { state: "on-phone", message: "The call is on your phone.", codec: "" } }} live client={c} />);
    expect(screen.queryByRole("button", { name: "Move audio here" })).toBeNull();
  });

  it("answers here or on the phone from Phone → Calls, with the same phone action", async () => {
    const { client: c, call } = client();
    const features: PhoneFeatureState = { threads: [], messages: [], photos: [], files: [], calls: [{ device_id: "dev_phone", state: "ringing", number: "+15550100", name: "Test Caller" }] };
    const phone = { id: "dev_phone", name: "Test Phone", online: true, capabilities: ["calls", "call-control"] };
    render(<PhoneTabs features={features} phone={phone} client={c} callAudio={ready} />);
    openTab("Calls");
    fireEvent.click(await screen.findByRole("button", { name: "Answer here" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("phone.call", { device_id: "dev_phone", operation: "answer" }));
    fireEvent.click(screen.getByRole("button", { name: "Answer on phone" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("phone.call", { device_id: "dev_phone", operation: "answer", audio: "phone" }));
  });
});
