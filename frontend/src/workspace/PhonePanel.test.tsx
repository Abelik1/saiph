// SPDX-License-Identifier: AGPL-3.0-or-later
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PhonePanel } from "./PhonePanel";
import { PhoneTabs } from "./PhoneTabs";
import type { PhoneFeatureState } from "./PhoneTabs";
import type { Client } from "./types";
import { openTab } from "../test-helpers";

const empty: PhoneFeatureState = { threads: [], messages: [], calls: [], photos: [], files: [] };
const session = { source: "com.spotify.music", app: "Spotify", title: "Synthetic song", artist: "Synthetic artist", playing: true,
  can_play: true, can_pause: true, can_next: true, can_previous: false, can_seek: false, position_ms: 0, length_ms: 1000, volume: 50 };
const phone = (capabilities: string[]) => ({ id: "phone", name: "Galaxy", online: true, capabilities });

describe("Phone panel", () => {
  it("controls the phone's media and ringer", async () => {
    const call = vi.fn().mockResolvedValue({ queued: true });
    render(<PhonePanel features={{ ...empty, media: [{ device_id: "phone", sessions: [session] }], ringers: [{ device_id: "phone", mode: "ring" }] }}
      phone={phone(["media", "ringer"])} client={{ call } as unknown as Client} />);
    expect(screen.getByText("Synthetic song")).toBeVisible();
    expect(screen.getByRole("button", { name: "Previous track" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Pause" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("phone.media", { device_id: "phone", source: "com.spotify.music", action: "pause" }));
    expect(screen.getByRole("radio", { name: "Ring" })).toHaveAttribute("aria-checked", "true");
    fireEvent.click(screen.getByRole("radio", { name: "Silent" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("phone.ringer", { device_id: "phone", mode: "silent" }));
  });
  it("turns Find phone into Stop ringing while the phone rings", async () => {
    const call = vi.fn().mockResolvedValue({ queued: true });
    const { rerender } = render(<PhonePanel features={empty} phone={phone(["ring"])} client={{ call } as unknown as Client} />);
    fireEvent.click(screen.getByRole("button", { name: "Find phone" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("phone.ring", { device_id: "phone" }));
    rerender(<PhonePanel features={empty} phone={{ ...phone(["ring"]), ringing: true }} client={{ call } as unknown as Client} />);
    const stop = screen.getByRole("switch", { name: "Stop ringing" });
    expect(stop).toHaveAttribute("aria-checked", "true");
    expect(screen.queryByRole("button", { name: "Find phone" })).toBeNull();
    fireEvent.click(stop);
    await waitFor(() => expect(call).toHaveBeenCalledWith("phone.ring.stop", { device_id: "phone" }));
    // Stopped on the phone: the next state shows Find phone again.
    rerender(<PhonePanel features={empty} phone={{ ...phone(["ring"]), ringing: false }} client={{ call } as unknown as Client} />);
    expect(screen.getByRole("button", { name: "Find phone" })).toBeVisible();
  });
  it("shows nothing when the phone offers neither", () => {
    const { container } = render(<PhonePanel features={empty} phone={phone([])} client={{ call: vi.fn() } as unknown as Client} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("New messages and calls", () => {
  it("suggests contacts from the phone and sends to a new number", async () => {
    vi.useFakeTimers();
    const call = vi.fn().mockResolvedValue({ queued: true });
    const features = { ...empty, contacts: [{ device_id: "phone", query: "Ali", contacts: [{ name: "Alice", numbers: ["+447700900123"] }] }] };
    render(<PhoneTabs features={features} phone={phone(["sms", "contacts"])} client={{ call } as unknown as Client} />);
    fireEvent.change(screen.getByLabelText("New message recipient"), { target: { value: "Ali" } });
    await act(async () => { vi.advanceTimersByTime(350); });
    expect(call).toHaveBeenCalledWith("phone.contacts.search", { device_id: "phone", query: "Ali" });
    vi.useRealTimers();
    fireEvent.click(screen.getByRole("button", { name: "Alice · +447700900123" }));
    fireEvent.change(screen.getByLabelText("New message text"), { target: { value: "Hello" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("phone.sms.compose", { device_id: "phone", address: "+447700900123", text: "Hello" }));
  });
  it("dials and calls back from recent calls", async () => {
    const call = vi.fn().mockResolvedValue({ queued: true });
    const features = { ...empty, call_logs: [{ device_id: "phone", calls: [{ number: "+447700900123", name: "Alice", timestamp: 1, duration: 3, type: "missed" as const }] }] };
    render(<PhoneTabs features={features} phone={phone(["calls", "call-dial", "call-log"])} client={{ call } as unknown as Client} />);
    openTab("Calls");
    await waitFor(() => expect(call).toHaveBeenCalledWith("phone.calls.log", { device_id: "phone" }));
    fireEvent.click(screen.getByRole("button", { name: "Call back Alice" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("phone.dial", { device_id: "phone", number: "+447700900123" }));
    fireEvent.change(screen.getByLabelText("Number to call"), { target: { value: "01234 567890" } });
    fireEvent.click(screen.getByRole("button", { name: "Call on phone" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("phone.dial", { device_id: "phone", number: "01234 567890" }));
  });
});

describe("MMS pictures", () => {
  const base = { ...empty, threads: [{ id: "t", device_id: "phone", thread: 7, recipients: ["Alice"], message: { body: "", timestamp: 1 } }],
    messages: [{ id: "m", message_id: 31, device_id: "phone", thread: 7, body: "", timestamp: 1, direction: "incoming" as const }],
    attachments: [{ device_id: "phone", thread: 7, message: 31, parts: [{ part: 5, mime: "image/jpeg", name: "IMG.jpg" }] }] };
  it("fetches a picture only when asked", async () => {
    const call = vi.fn().mockResolvedValue({ queued: true });
    render(<PhoneTabs features={base} phone={phone(["sms"])} client={{ call } as unknown as Client} />);
    fireEvent.click(screen.getByRole("button", { name: "Show IMG.jpg" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("phone.sms.attachment", { device_id: "phone", thread: 7, message: 31, part: 5 }));
  });
  it("shows a received picture inline and saves it", async () => {
    const call = vi.fn().mockResolvedValue({ saved: true });
    const features = { ...base, attachment_files: [{ id: "a", device_id: "phone", thread: 7, message: 31, part: 5, name: "IMG.jpg", mime: "image/jpeg", size: 4, preview: "data:image/jpeg;base64,AA==", ready: true }] };
    render(<PhoneTabs features={features} phone={phone(["sms"])} client={{ call } as unknown as Client} />);
    expect(screen.getByAltText("IMG.jpg")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: /Save/ }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("phone.sms.attachment.save", { id: "a" }));
  });
});

describe("Phone apps", () => {
  it("shows apps as tiles, filters, opens, pins and adds a menu shortcut", async () => {
    const call = vi.fn(async (method: string, args?: Record<string, unknown>) => method === "phone.apps"
      ? { apps: [{ package: "com.spotify.music", name: "Spotify", system: false }, { package: "com.android.settings", name: "Settings", system: true }],
        pinned: [], usage: {}, icons: false }
      : method === "phone.app.favorite" ? { pinned: args?.pinned ? [args.package] : [] } : { opened: true });
    render(<PhoneTabs features={empty} phone={phone([])} client={{ call } as unknown as Client} />);
    openTab("Apps");
    await waitFor(() => expect(screen.getByRole("button", { name: "Open Spotify" })).toBeVisible());
    expect(screen.getByRole("list", { name: "All apps" })).toBeVisible();
    fireEvent.change(screen.getByLabelText("Find a phone app"), { target: { value: "spot" } });
    expect(screen.queryByRole("button", { name: "Open Settings" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Open Spotify" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("phone.app.open", { device_id: "phone", package: "com.spotify.music", name: "Spotify" }));
    fireEvent.change(screen.getByLabelText("Find a phone app"), { target: { value: "" } });
    // Opening counts locally, so the app appears under Most used straight away.
    expect(within(screen.getByRole("list", { name: "Most used apps" })).getByRole("button", { name: "Open Spotify" })).toBeVisible();
    fireEvent.contextMenu(screen.getAllByRole("button", { name: "Open Spotify" })[0]);
    fireEvent.click(await screen.findByRole("menuitem", { name: "Pin to the top" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("phone.app.favorite", { device_id: "phone", package: "com.spotify.music", pinned: true }));
    expect(await screen.findByRole("list", { name: "Pinned apps" })).toBeVisible();
    fireEvent.contextMenu(within(screen.getByRole("list", { name: "Pinned apps" })).getByRole("button", { name: "Open Spotify" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: /Add to (Start|apps) menu/ }));
    await waitFor(() => expect(screen.getByText("Spotify was added to your apps menu.")).toBeVisible());
    expect(call).toHaveBeenCalledWith("phone.app.pin", { package: "com.spotify.music", name: "Spotify" });
  });
  it("waits for the phone's Cloud answer without any USB debugging", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    try {
      let answers = 0;
      const call = vi.fn(async (method: string) => method === "phone.apps"
        ? (++answers < 3 ? { pending: true, source: "cloud" } : { apps: [{ package: "com.example.maps", name: "Maps", system: false }] })
        : { live: false, session: "a".repeat(32) });
      render(<PhoneTabs features={empty} phone={phone([])} client={{ call } as unknown as Client} />);
      openTab("Apps");
      await act(async () => { await vi.advanceTimersByTimeAsync(0); });
      expect(screen.getByText("Asking your phone for its apps…")).toBeVisible();
      await act(async () => { await vi.advanceTimersByTimeAsync(4100); });
      expect(screen.getByRole("button", { name: "Open Maps" })).toBeVisible();
      expect(call.mock.calls.filter(([method]) => method === "phone.apps")).toHaveLength(3);
      expect(call.mock.calls.some(([method]) => String(method).endsWith(".legacy"))).toBe(false);
      fireEvent.click(screen.getByRole("button", { name: "Open Maps" }));
      await act(async () => { await vi.advanceTimersByTimeAsync(0); });
      expect(call).toHaveBeenCalledWith("phone.app.open", { device_id: "phone", package: "com.example.maps", name: "Maps" });
      expect(screen.getByText("Opening Maps once you start sharing on your phone.")).toBeVisible();
    } finally { vi.useRealTimers(); }
  });
  it("offers no scrcpy route unless USB debugging is turned on in Settings → Advanced", async () => {
    const call = vi.fn(async (method: string) => method === "phone.apps" ? { apps: [{ package: "com.spotify.music", name: "Spotify", system: false }] } : { opened: true });
    render(<PhoneTabs features={empty} phone={phone([])} client={{ call } as unknown as Client} />);
    openTab("Apps");
    await waitFor(() => expect(screen.getByRole("button", { name: "Open Spotify" })).toBeVisible());
    expect(screen.queryByRole("button", { name: "Use USB debugging (scrcpy)" })).toBeNull();
    expect(screen.queryByText(/scrcpy/i)).toBeNull();
  });
  it("keeps scrcpy windows as an advanced choice", async () => {
    const call = vi.fn(async (method: string) => method === "phone.apps" ? { unavailable: true, message: "Start the phone screen to list its apps, or update Saiph on your phone." }
      : method === "phone.apps.legacy" ? { apps: [{ package: "com.spotify.music", name: "Spotify", system: false }] } : { opened: true });
    render(<PhoneTabs features={empty} phone={phone([])} client={{ call } as unknown as Client} usbDebugging />);
    openTab("Apps");
    expect(await screen.findByText(/Start the phone screen to list its apps/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Use USB debugging (scrcpy)" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Open Spotify" })).toBeVisible());
    expect(screen.queryByRole("button", { name: "Show phone screen" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Open Spotify" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("phone.app.open.legacy", { device_id: "phone", package: "com.spotify.music", name: "Spotify" }));
  });
  it("switches to Apps when a pinned phone app opens the screen", async () => {
    const call = vi.fn(async () => ({ pending: true }));
    const status = { state: "idle" as const, running: false, waiting: false, message: "", resolution: "1080p" as const, fps: 20 as const,
      quality: "high" as const, input: false, delivered: false, device_id: null, launch: "", reveal: 0 };
    const { rerender } = render(<PhoneTabs features={empty} phone={phone([])} client={{ call } as unknown as Client} screen={status} />);
    expect(screen.getByRole("tab", { name: /Messages/ })).toHaveAttribute("aria-selected", "true");
    rerender(<PhoneTabs features={empty} phone={phone([])} client={{ call } as unknown as Client} screen={{ ...status, reveal: 1 }} />);
    await waitFor(() => expect(screen.getByRole("tab", { name: /Apps/ })).toHaveAttribute("aria-selected", "true"));
  });
});
