// SPDX-License-Identifier: AGPL-3.0-or-later
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PhonePanel } from "./PhonePanel";
import { PhoneTabs } from "./PhoneTabs";
import type { PhoneFeatureState } from "./PhoneTabs";
import type { Client } from "./types";

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
    expect(screen.getByRole("button", { name: "Ring" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Silent" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("phone.ringer", { device_id: "phone", mode: "silent" }));
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
    fireEvent.click(screen.getByRole("button", { name: "Calls" }));
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
