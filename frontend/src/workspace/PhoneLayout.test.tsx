// SPDX-License-Identifier: AGPL-3.0-or-later
// The phone page's newer behaviour: undoable dismissal, keyboard sending and
// shortcuts, a confirmed clear, and the app-wide incoming-call bar.
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { Phone } from "./Phone";
import { PhoneTabs, type PhoneFeatureState } from "./PhoneTabs";
import { YourWeek } from "./YourWeek";
import type { Client, State } from "./types";

const phone = { id: "phone", name: "Synthetic phone", online: true, last_seen_at: null, capabilities: ["battery", "notifications", "sms", "calls", "call-control"], battery: { battery_level: 50, is_charging: false, updated_at: 1 } };
const notification = (id: string, title: string) => ({ id, device_id: "phone", key: id, app: "Messages", package: "test", title, text: "Synthetic body", timestamp: 1, actions: [] });
function state(): State {
  return {
    settings: { hub: { paired: true, device_id: "desktop", base_url: "" }, link: { camera: { enabled: false } }, machine: { name: "Synthetic desktop" } },
    hub_inbox: { items: [], synced_at: null, error: "" },
    phone: { status: "Online", error: "", devices: [phone], notifications: [notification("a", "First note"), notification("b", "Second note")] },
  } as unknown as State;
}
const features: PhoneFeatureState = {
  threads: [{ id: "t", device_id: "phone", thread: 7, recipients: ["Synthetic sender"], message: { body: "Hello", timestamp: 1 } }],
  messages: [{ id: "m", device_id: "phone", thread: 7, body: "Hello", timestamp: 1, direction: "incoming" }],
  calls: [], photos: [], files: [],
};

afterEach(() => vi.useRealTimers());

describe("Dismissing notifications", () => {
  it("waits for Undo before dismissing on every device", () => {
    vi.useFakeTimers();
    const call = vi.fn().mockResolvedValue({});
    render(<Phone state={state()} client={{ call, subscribe: () => () => {} } as Client} />);
    fireEvent.click(screen.getAllByRole("button", { name: "Dismiss on all devices" })[0]);
    expect(screen.queryByText("First note")).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent("Notification dismissed on all devices.");
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(screen.getByText("First note")).toBeVisible();
    act(() => vi.advanceTimersByTime(6000));
    expect(call).not.toHaveBeenCalled();
  });

  it("clears all after the undo window", () => {
    vi.useFakeTimers();
    const call = vi.fn().mockResolvedValue({});
    render(<Phone state={state()} client={{ call, subscribe: () => () => {} } as Client} />);
    fireEvent.click(screen.getByRole("button", { name: "Clear all" }));
    expect(screen.getByRole("status")).toHaveTextContent("2 notifications dismissed");
    act(() => vi.advanceTimersByTime(5000));
    expect(call).toHaveBeenCalledWith("phone.notification", { id: "a", operation: "dismiss" });
    expect(call).toHaveBeenCalledWith("phone.notification", { id: "b", operation: "dismiss" });
  });
});

describe("Phone tabs from the keyboard", () => {
  it("sends with Enter and keeps Shift+Enter for a new line", async () => {
    const call = vi.fn().mockResolvedValue({ queued: true });
    render(<PhoneTabs features={features} phone={phone} client={{ call } as unknown as Client} />);
    const field = screen.getByLabelText("SMS reply");
    fireEvent.change(field, { target: { value: "On my way" } });
    fireEvent.keyDown(field, { key: "Enter", shiftKey: true });
    expect(call).not.toHaveBeenCalledWith("phone.sms.send", expect.anything());
    fireEvent.keyDown(field, { key: "Enter" });
    await waitFor(() => expect(call).toHaveBeenCalledWith("phone.sms.send", { device_id: "phone", thread: 7, text: "On my way" }));
  });

  it("opens tabs with Ctrl and a number, and a new message with Ctrl+N", () => {
    render(<PhoneTabs features={features} phone={phone} client={{ call: vi.fn().mockResolvedValue({}) } as unknown as Client} />);
    fireEvent.keyDown(window, { key: "3", ctrlKey: true });
    expect(screen.getByRole("tab", { name: "Calls" })).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(window, { key: "n", ctrlKey: true });
    expect(screen.getByRole("tab", { name: "Messages" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByLabelText("New message recipient")).toHaveFocus();
  });
});

describe("Your week", () => {
  it("asks before clearing the week", async () => {
    const call = vi.fn().mockResolvedValue({ enabled: true, actions: 3, busiest_day: null, screen: null, top: [], people: [] });
    render(<YourWeek enabled client={{ call } as unknown as Client} />);
    const details = screen.getByText("Your week").closest("details")!;
    details.open = true;
    fireEvent(details, new Event("toggle"));
    fireEvent.click(await screen.findByRole("button", { name: "Clear this week" }));
    expect(call).not.toHaveBeenCalledWith("insights.clear");
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("insights.clear"));
  });
});

describe("Incoming calls", () => {
  it("shows a ringing call on every page and answers it from there", async () => {
    const ringing = { ...state(), phone_features: { ...features, calls: [{ device_id: "phone", state: "ringing", number: "+15550000000", name: "Synthetic caller" }] } } as unknown as State;
    const call = vi.fn(async (method: string) => method === "state" ? ringing : {});
    render(<App providedClient={{ call, subscribe: () => () => {} } as unknown as Client} />);
    const bar = await screen.findByRole("alert");
    expect(bar).toHaveTextContent("Incoming call · Synthetic caller on Synthetic phone");
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    expect(screen.getByRole("alert")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Answer" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("phone.call", { device_id: "phone", operation: "answer" }));
  });
});
