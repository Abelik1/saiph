// SPDX-License-Identifier: AGPL-3.0-or-later
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Phone } from "./Phone";
import { PhonePanel, quickHint } from "./PhonePanel";
import { PhoneSettings } from "./PhoneSettings";
import { HelpFeedback, topics } from "./HelpFeedback";
import { hiddenTabs, phonePreferences } from "./phonePreferences";
import type { Client, PhoneStatus, State } from "./types";

const status: PhoneStatus = { battery: 76, charging: true, wifi: true, cellular: false, metered: false, bluetooth: false, signal: 2,
  ringer: "vibrate", dnd: false, controls: ["status", "ring", "ringer", "dnd", "media", "hotspot", "mobile_data"], mobile_data: true, paused: false };

function cloudPhone(changes: Record<string, unknown> = {}) {
  return { id: "cloud", name: "Synthetic Pixel", online: true, last_seen_at: null, hosted: true,
    capabilities: ["files", "calls", ...status.controls], battery: { battery_level: 76, is_charging: true }, status, wallpaper: null, ...changes };
}

function state(phone = cloudPhone(), link: object = {}): State {
  return {
    hub_inbox: { items: [], synced_at: null, error: "" },
    platform: "windows",
    settings: { link, hosted: { enabled: true } },
    hosted: { enabled: true, notifications: [] },
    phone: { status: "Online", error: "", devices: [phone], notifications: [] },
  } as unknown as State;
}

const client = (call = vi.fn().mockResolvedValue({ queued: true })) => ({ call, subscribe: () => () => {} }) as unknown as Client;

describe("Phone Link device header", () => {
  it("draws Wi-Fi bars from the Wi-Fi level and mobile bars from the cellular level", () => {
    // On Wi-Fi at about 2 of 4 bars, with the SIM registered at 3 of 4: both show, as on the phone.
    const { rerender } = render(<Phone state={state(cloudPhone({ status: { ...status, wifi: true, cellular: false, signal: 1 },
      signal: { wifi_level: 2, cellular_level: 3 } }))} client={client()} />);
    expect(screen.getByRole("img", { name: "Wi-Fi signal 2 of 4" })).toBeVisible();
    expect(screen.getByRole("img", { name: "Mobile signal 3 of 4" })).toBeVisible();
    expect(screen.queryByRole("img", { name: "Wi-Fi connected" })).toBeNull();
    // Off Wi-Fi with no mobile service.
    rerender(<Phone state={state(cloudPhone({ signal: { wifi_level: null, cellular_level: null } }))} client={client()} />);
    expect(screen.getByRole("img", { name: "Wi-Fi not connected" })).toBeVisible();
    expect(screen.queryByRole("img", { name: /Mobile signal/ })).toBeNull();
  });
  it("shows battery, Wi-Fi, Bluetooth and signal from a Cloud phone, with Refresh", async () => {
    const call = vi.fn().mockResolvedValue({ queued: true });
    render(<Phone state={state()} client={client(call)} />);
    expect(screen.getByText("76%")).toBeVisible();
    expect(screen.getByText("· charging")).toBeVisible();
    expect(screen.getByRole("img", { name: "Wi-Fi connected" })).toBeVisible();
    expect(screen.getByRole("img", { name: "Bluetooth off" })).toBeVisible();
    expect(screen.getByRole("img", { name: "Mobile signal 2 of 4" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Refresh phone status" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("phone.refresh", { device_id: "cloud" }));
  });
  it("greys out actions offline and explains a pause on mobile data", () => {
    render(<Phone state={state(cloudPhone({ online: false, status: { ...status, paused: true, mobile_data: false } }))} client={client()} />);
    expect(screen.getByRole("button", { name: "Refresh phone status" })).toBeDisabled();
    expect(screen.getByText(/Sync over mobile data is off on your phone/)).toBeVisible();
    expect(screen.queryByRole("img", { name: "Wi-Fi connected" })).toBeNull();
  });
  it("uses the wallpaper only when opted in", () => {
    const wallpaper = "data:image/jpeg;base64,/9j/2Q==";
    const { rerender } = render(<Phone state={state(cloudPhone({ wallpaper }))} client={client()} />);
    expect(screen.queryByTestId("phone-wallpaper")).toBeNull();
    rerender(<Phone state={state(cloudPhone({ wallpaper }), { phone: { wallpaper: true } })} client={client()} />);
    expect(screen.getByTestId("phone-wallpaper")).toBeInTheDocument();
  });
  it("hides turned-off features", () => {
    render(<Phone state={state(cloudPhone(), { phone: { features: { notifications: false, photos: false, apps: false } } })} client={client()} />);
    expect(screen.getByText("Notifications are turned off in Settings → Phone.")).toBeVisible();
    expect(screen.queryByRole("tab", { name: /Photos/ })).toBeNull();
    expect(screen.queryByRole("tab", { name: /Apps/ })).toBeNull();
    expect(screen.getByRole("tab", { name: /Messages/ })).toBeVisible();
  });
});

describe("Quick actions", () => {
  it("toggles the phone's Do Not Disturb and finds the phone", async () => {
    const call = vi.fn().mockResolvedValue({ queued: true });
    render(<PhonePanel phone={cloudPhone()} client={client(call)} />);
    const dnd = screen.getByRole("switch", { name: "Do Not Disturb" });
    expect(dnd).toHaveAttribute("aria-checked", "false");
    fireEvent.click(dnd);
    await waitFor(() => expect(call).toHaveBeenCalledWith("phone.dnd", { device_id: "cloud", active: true }));
    fireEvent.click(screen.getByRole("button", { name: "Find phone" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("phone.ring", { device_id: "cloud" }));
  });
  it("explains missing Android access and hides the audio player when turned off", () => {
    const limited = cloudPhone({ status: { ...status, controls: ["status", "ring"] }, capabilities: ["files", "status", "ring"] });
    expect(quickHint(limited)).toMatch(/Do Not Disturb access .* and notification access/);
    const session = { source: "org.example.player", app: "Synthetic Player", title: "Test Track", artist: "", playing: true,
      can_play: true, can_pause: true, can_next: true, can_previous: false, can_seek: false, position_ms: 0, length_ms: 0, volume: 0 };
    const features = { threads: [], messages: [], calls: [], photos: [], files: [], media: [{ device_id: "cloud", sessions: [session] }] };
    const { rerender } = render(<PhonePanel features={features} phone={cloudPhone()} client={client()} />);
    expect(screen.getByText("Test Track")).toBeVisible();
    rerender(<PhonePanel features={features} phone={cloudPhone()} client={client()} audio={false} />);
    expect(screen.queryByText("Test Track")).toBeNull();
    expect(quickHint(cloudPhone({ online: false }))).toBe("Reconnect your phone to use quick actions.");
  });
});

describe("Settings → Phone", () => {
  it("defaults everything on except the wallpaper", () => {
    const preferences = phonePreferences({ link: { phone: { features: { photos: false } } } } as unknown as State["settings"]);
    expect(preferences).toMatchObject({ wallpaper: false, audio_player: true, badges: true, recent: true });
    expect(hiddenTabs(preferences)).toEqual(["Photos"]);
  });
  it("saves feature switches and acts on the phone", async () => {
    const call = vi.fn().mockResolvedValue({});
    render(<PhoneSettings state={state()} client={client(call)} />);
    fireEvent.click(screen.getByRole("switch", { name: "Messages" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("settings.save", { link: { phone: { features: { messages: false } } } }));
    fireEvent.click(screen.getByRole("switch", { name: "Sync over mobile data" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("phone.mobile_data", { device_id: "cloud", allowed: false }));
    fireEvent.click(screen.getByRole("button", { name: "Open on phone" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("phone.hotspot", { device_id: "cloud" }));
    fireEvent.click(screen.getByRole("button", { name: "Open folder" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("phone.files.folder"));
  });
  it("shows Calls off and disabled when no phone shares calls, and why", () => {
    render(<PhoneSettings state={state(cloudPhone({ capabilities: ["files"] }))} client={client()} />);
    const calls = screen.getByRole("switch", { name: "Calls" });
    expect(calls).toBeDisabled();
    expect(calls).toHaveAttribute("aria-checked", "false");
    expect(screen.getByText(/turn on Texts and calls/)).toBeVisible();
    expect(screen.getByRole("switch", { name: "Sync over mobile data" })).toBeDisabled();
  });
  it("asks for the wallpaper once it is turned on", async () => {
    const call = vi.fn().mockResolvedValue({});
    const phone = cloudPhone({ capabilities: ["files", ...status.controls, "wallpaper"] });
    render(<PhoneSettings state={state(phone)} client={client(call)} />);
    fireEvent.click(screen.getByRole("switch", { name: "Use phone wallpaper" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("phone.wallpaper", { device_id: "cloud" }));
    expect(call).toHaveBeenCalledWith("settings.save", { link: { phone: { wallpaper: true } } });
  });
});

describe("Self-hosted Hub phones (shared status layer)", () => {
  // A Hub phone: no `hosted` flag; the desktop merges its status controls into its capabilities.
  const hubControls = ["status", "ring", "ringer", "dnd", "media", "hotspot"];
  const hubPhone = (changes: Record<string, unknown> = {}) => cloudPhone({ id: "hub", hosted: undefined,
    capabilities: ["battery", "notifications", "files", ...hubControls], status: { ...status, controls: hubControls }, ...changes });
  const hubState = (phone = hubPhone()) => ({ ...state(phone), settings: { link: {} }, hosted: undefined, hub: { paired: true } }) as unknown as State;
  it("shows the Wi-Fi, Bluetooth and signal header and Refresh", async () => {
    const call = vi.fn().mockResolvedValue({ queued: true });
    render(<Phone state={hubState()} client={client(call)} />);
    expect(screen.getByRole("img", { name: "Wi-Fi connected" })).toBeVisible();
    expect(screen.getByRole("img", { name: "Mobile signal 2 of 4" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Refresh phone status" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("phone.refresh", { device_id: "hub" }));
  });
  it("offers Do Not Disturb, the same access hints and the hotspot", async () => {
    const call = vi.fn().mockResolvedValue({ queued: true });
    render(<PhonePanel phone={hubPhone()} client={client(call)} />);
    fireEvent.click(screen.getByRole("switch", { name: "Do Not Disturb" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("phone.dnd", { device_id: "hub", active: true }));
    expect(quickHint(hubPhone({ capabilities: ["battery", "status", "ring"], status: { ...status, controls: ["status", "ring"] } })))
      .toMatch(/Do Not Disturb access .* and notification access/);
    // An older Hub phone without a status keeps its previous quick actions and no hint.
    expect(quickHint(hubPhone({ status: null }))).toBe("");
  });
  it("keeps mobile data for Saiph Cloud and asks a Hub phone for its wallpaper", async () => {
    const call = vi.fn().mockResolvedValue({});
    const withWallpaper = hubPhone({ capabilities: ["battery", ...hubControls, "wallpaper"] });
    render(<PhoneSettings state={hubState(withWallpaper)} client={client(call)} />);
    expect(screen.getByRole("switch", { name: "Sync over mobile data" })).toBeDisabled();
    fireEvent.click(screen.getByRole("switch", { name: "Use phone wallpaper" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("phone.wallpaper", { device_id: "hub" }));
    fireEvent.click(screen.getByRole("button", { name: "Open on phone" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("phone.hotspot", { device_id: "hub" }));
  });
  it("explains a missing wallpaper by phone version or Android access", () => {
    const on = (phone: ReturnType<typeof hubPhone>) => ({ ...hubState(phone), settings: { link: { phone: { wallpaper: true } } } }) as unknown as State;
    const { unmount } = render(<PhoneSettings state={on(hubPhone({ status: null, capabilities: ["battery", "ring"] }))} client={client()} />);
    expect(screen.getByText("Update Saiph on your phone to show its wallpaper here.")).toBeVisible();
    unmount();
    render(<PhoneSettings state={on(hubPhone())} client={client()} />);
    expect(screen.getByText(/needs All files access/)).toBeVisible();
  });
});

describe("Help & feedback", () => {
  it("opens feedback and the guide from a fixed list and covers every area", async () => {
    const call = vi.fn().mockResolvedValue({});
    render(<HelpFeedback client={client(call)} />);
    expect(topics.map(([title]) => title)).toEqual(["General", "Apps", "Calls", "Messages", "Notifications", "Phone screen", "Photos"]);
    fireEvent.click(screen.getByRole("button", { name: "Send feedback" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("help.open", { link: "feedback" }));
    fireEvent.click(screen.getByRole("button", { name: "Read the full guide" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("help.open", { link: "guide" }));
  });
});
