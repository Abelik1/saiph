// SPDX-License-Identifier: AGPL-3.0-or-later
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { Phone } from "./Phone";
import { PhoneTabs, type PhoneFeatureState } from "./PhoneTabs";
import type { Client, State } from "./types";
import { openTab } from "../test-helpers";

// Synthetic Saiph Hosted phone: no battery capability, marked hosted by the computer.
const hostedPhone = {
  id: "dev_hosted",
  name: "Synthetic phone",
  online: true,
  last_seen_at: "2026-10-14T09:00:00Z",
  hosted: true,
  capabilities: ["files", "sms", "calls", "call-control", "call-dial", "contacts"],
};
const features: PhoneFeatureState = {
  threads: [{ id: "t", device_id: "dev_hosted", thread: 7, recipients: ["+15550100"], message: { body: "Synthetic SMS", timestamp: 1 } }],
  messages: [{ id: "m", message_id: 41, device_id: "dev_hosted", thread: 7, body: "Synthetic SMS", timestamp: 1, direction: "incoming" }],
  calls: [{ device_id: "dev_hosted", state: "ringing", number: "+15550100", name: "Synthetic Caller" }],
  photos: [],
  files: [],
};
function hostedState(device: Partial<typeof hostedPhone> | null = {}): State {
  return {
    hub_inbox: { items: [], synced_at: null, error: "" },
    hosted: { available: true, enabled: true, status: "active", identity: true },
    settings: { hub: { paired: false, base_url: "", device_id: "" } },
    phone: { status: "Unpaired", error: "", notifications: [], devices: device ? [{ ...hostedPhone, ...device }] : [] },
    phone_features: features,
  } as unknown as State;
}
const client = (call = vi.fn().mockResolvedValue({ queued: true })) => ({ call, subscribe: () => () => {} }) as unknown as Client;

describe("Saiph Hosted phone on the Phone page", () => {
  it("lists an approved hosted phone and points notifications to Hosted settings", () => {
    render(<Phone state={hostedState()} client={client()} />);
    expect(screen.getByRole("heading", { name: "Synthetic phone" })).toBeVisible();
    expect(screen.getByText("Online")).toBeVisible();
    expect(screen.getByText(/notifications appear in Settings → Saiph Hosted/)).toBeVisible();
    // The Link clipboard helper hint does not apply to a hosted phone.
    expect(screen.queryByText(/Clipboard isn't shared/)).toBeNull();
    expect(screen.getByText("Synthetic SMS", { selector: "p" })).toBeVisible();
  });
  it("explains how a hosted phone appears before it shares texts or calls", () => {
    render(<Phone state={hostedState(null)} client={client()} />);
    expect(screen.getByText(/turn on Texts and calls in Saiph Hosted on the phone/)).toBeVisible();
    expect(screen.getByText("Pair once to get started")).toBeVisible();
  });
  it("keeps saved texts while offline and names Saiph Hosted as the connection", () => {
    render(<Phone state={hostedState({ online: false })} client={client()} />);
    expect(screen.getByText(/check that Saiph Hosted is connected/)).toBeVisible();
    expect(screen.getByText("Synthetic SMS", { selector: "p" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  });
  it("replies, starts a new text and answers a call through the shared actions", async () => {
    const call = vi.fn().mockResolvedValue({ queued: true });
    render(<PhoneTabs features={features} phone={hostedPhone} client={client(call)} />);
    await waitFor(() => expect(call).toHaveBeenCalledWith("phone.sms.open", { device_id: "dev_hosted", thread: 7 }));
    fireEvent.change(screen.getByLabelText("SMS reply"), { target: { value: "Synthetic reply" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("phone.sms.send", { device_id: "dev_hosted", thread: 7, text: "Synthetic reply" }));
    fireEvent.click(screen.getByRole("button", { name: "New message" }));
    fireEvent.change(screen.getByLabelText("New message recipient"), { target: { value: "+15550101" } });
    fireEvent.change(screen.getByLabelText("New message text"), { target: { value: "Synthetic hello" } });
    fireEvent.click(screen.getAllByRole("button", { name: "Send" })[0]);
    await waitFor(() => expect(call).toHaveBeenCalledWith("phone.sms.compose", { device_id: "dev_hosted", address: "+15550101", text: "Synthetic hello" }));
    openTab("Calls");
    expect(screen.getByText("Synthetic Caller")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Answer" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("phone.call", { device_id: "dev_hosted", operation: "answer" }));
    fireEvent.change(screen.getByLabelText("Number to call"), { target: { value: "+15550100" } });
    fireEvent.click(screen.getByRole("button", { name: "Call on phone" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("phone.dial", { device_id: "dev_hosted", number: "+15550100" }));
  });
  it("hides actions the hosted phone does not offer and explains its own switch", () => {
    const limited = { ...hostedPhone, capabilities: ["files"] };
    render(<PhoneTabs features={features} phone={limited} client={client()} />);
    expect(screen.getByText(/Turn on Texts and calls in Saiph Hosted on your phone and allow SMS/)).toBeVisible();
    openTab("Calls");
    expect(screen.getByText(/Turn on Texts and calls in Saiph Hosted on your phone and allow phone access/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Answer" })).toBeNull();
  });
  it("stops offering answer once another computer handled the call and says which", () => {
    const handled = { ...features, calls: [{ ...features.calls[0], state: "active" as const, handled: "answer" as const, handled_by: "Synthetic laptop" }] };
    render(<PhoneTabs features={handled} phone={hostedPhone} client={client()} />);
    openTab("Calls");
    expect(screen.getByText("Call in progress")).toBeVisible();
    expect(screen.getByText("Answered on Synthetic laptop")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Answer" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Decline" })).toBeNull();
  });
  it("shows a lost race or a refused dial as a plain note, not an error", () => {
    const declined = { ...features, calls: [{ ...features.calls[0], state: "ended" as const, handled: "reject" as const, handled_by: "Synthetic laptop" }] };
    render(<PhoneTabs features={declined} phone={{ ...hostedPhone, call_notice: "Not dialed: your phone is already on a call." }} client={client()} />);
    openTab("Calls");
    expect(screen.getByText("Not dialed: your phone is already on a call.")).toHaveAttribute("role", "status");
    expect(screen.getByText("Declined on Synthetic laptop")).toBeVisible();
    expect(screen.queryByRole("alert")).toBeNull();
  });
  it("keeps group threads on the phone without suggesting an update", () => {
    const group = { ...features, threads: [{ ...features.threads[0], recipients: ["+15550100", "+15550101"] }] };
    render(<PhoneTabs features={group} phone={hostedPhone} client={client()} />);
    expect(screen.getByText("Group replies stay in your phone's messaging app with Saiph Hosted.")).toBeVisible();
    expect(screen.getByLabelText("SMS reply")).toBeDisabled();
  });
});
