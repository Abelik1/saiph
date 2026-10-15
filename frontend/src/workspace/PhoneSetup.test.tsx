// SPDX-License-Identifier: AGPL-3.0-or-later
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import App from "../App";
import { Phone } from "./Phone";
import { HostedPhoneSetup, PhoneSetup } from "./PhoneSetup";
import { HostedApproveDevice } from "./HostedSettings";
import type { Client, State } from "./types";

const account = { status: "signed_in", error: "", refresh_tokens: false };
const rootCode = { code: "orion-root-v1:synthetic", fingerprint: "AAAA BBBB CCCC DDDD", expires_at: "2030-01-01T00:00:00Z", expires_in: 300, modules: Array.from({ length: 29 }, () => "0".repeat(29)) };
const offered = { code: "orion-approve-v1:synthetic", device_id: "synthetic-phone", fingerprint: "1111 2222 3333 4444", expires_at: 1900000000 };
function state(ready = false): State {
  return { hub_inbox: { items: [], synced_at: null, error: "" }, settings: { hub: { paired: false, base_url: "", device_id: "" }, machine: { name: "Synthetic desktop" }, link: {} },
    hosted: { available: true, configured: true, enabled: ready, identity: ready, status: ready ? "active" : "off", role: ready ? "root" : null,
      ...(ready ? { account, roster: { expires_at: 1900000000, version: 1, clock_warning: false, members: [] } } : {}) },
    setup: { show: !ready, mode: null, completed: false, connected: ready, tools: {}, linux: {}, platform: "windows" },
    phone: { devices: [], notifications: [], error: "", status: "" },
  } as unknown as State;
}
function client(call = vi.fn().mockResolvedValue({})): Client { return { call, subscribe: () => () => {} } as Client; }

describe("Phone setup", () => {
  it("starts with sign-in and only enables the account when asked", async () => {
    const bridge = client();
    render(<Phone state={state()} client={bridge} />);
    expect(screen.getByRole("heading", { name: "Connect your phone" })).toBeVisible();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("tab", { name: /Messages/ })).toBeNull();
    expect(bridge.call).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Sign in to Saiph" }));
    await waitFor(() => expect(bridge.call).toHaveBeenCalledWith("hosted.sign_in"));
    expect(bridge.call).toHaveBeenCalledWith("hosted.enable", { enabled: true });
    expect(bridge.call).not.toHaveBeenCalledWith("hosted.setup_root");
  });
  it("requires an explicit main-computer choice after signing in", async () => {
    const value = state();
    value.hosted = { ...value.hosted!, enabled: true, account };
    const bridge = client();
    render(<PhoneSetup state={value} client={bridge} />);
    expect(bridge.call).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Set up this computer" }));
    await waitFor(() => expect(bridge.call).toHaveBeenCalledWith("hosted.setup_root"));
  });
  it("shows the QR automatically, moves on when the phone's request arrives and keeps full-code approval explicit", async () => {
    let requests: typeof offered[] = [];
    const call = vi.fn(async (method: string) => method === "hosted.root_code" ? rootCode : method === "hosted.requests" ? { requests } : {});
    const bridge = client(call);
    const initial = state(true);
    const view = render(<Phone state={initial} client={bridge} />);
    expect(await screen.findByRole("img", { name: "Hosted root approval QR code" })).toBeVisible();
    expect(screen.getByText(rootCode.fingerprint)).toBeVisible();
    expect(screen.queryByLabelText("Device request code")).toBeNull();
    await waitFor(() => expect(call).toHaveBeenCalledWith("hosted.requests"));
    expect(screen.getByRole("heading", { name: "Scan on your phone" })).toBeVisible();
    // The phone scans: its request appears and the wizard advances without a click.
    requests = [offered];
    expect(await screen.findByRole("heading", { name: "Approve your phone" }, { timeout: 6000 })).toHaveFocus();
    expect(screen.queryByRole("img", { name: "Hosted root approval QR code" })).toBeNull();
    fireEvent.click(await screen.findByRole("button", { name: "Review and approve" }));
    expect(screen.getByText(offered.fingerprint)).toBeVisible();
    fireEvent.change(screen.getByLabelText("Device name"), { target: { value: "My phone" } });
    expect(screen.getByRole("button", { name: "Approve device" })).toBeDisabled();
    expect(call).not.toHaveBeenCalledWith("hosted.approve", expect.anything());
    fireEvent.click(screen.getByLabelText("Every group matches my device"));
    fireEvent.click(screen.getByRole("button", { name: "Approve device" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("hosted.approve", { code: offered.code, label: "My phone", confirmed: true }));
    // Approval is not connection: the wizard waits, says when the phone connects, and leaves on Done.
    expect(await screen.findByRole("heading", { name: "Phone approved" })).toBeVisible();
    expect(screen.getByText("Waiting for your phone to connect…")).toBeVisible();
    const connected = { ...initial, phone: { ...initial.phone!, devices: [{ id: offered.device_id, name: "My phone", hosted: true, online: true, last_seen_at: null, capabilities: ["files"] }] } };
    view.rerender(<Phone state={connected} client={bridge} />);
    expect(screen.getByRole("heading", { name: "Phone connected" })).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent("My phone is connected");
    expect(screen.queryByRole("heading", { name: "My phone" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.queryByRole("img", { name: "Hosted root approval QR code" })).toBeNull();
    expect(screen.getByRole("heading", { name: "My phone" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Connect a phone" })).toBeVisible();
    expect(screen.queryByLabelText("Quick controls")).toBeNull();
  }, 10000);
  it("clears a previous comparison when returning to scanning and waits there for a new request", async () => {
    const call = vi.fn(async (method: string) => method === "hosted.root_code" ? rootCode : { requests: [offered] });
    render(<PhoneSetup state={state(true)} client={client(call)} />);
    // The request is already waiting, so the wizard goes straight to Approve.
    await screen.findByRole("heading", { name: "Approve your phone" });
    fireEvent.click(await screen.findByRole("button", { name: "Review and approve" }));
    fireEvent.change(screen.getByLabelText("Device name"), { target: { value: "My phone" } });
    fireEvent.click(screen.getByLabelText("Every group matches my device"));
    expect(screen.getByRole("button", { name: "Approve device" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Back to scanning" }));
    expect(await screen.findByRole("img", { name: "Hosted root approval QR code" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Scan on your phone" })).toHaveFocus();
    // The same pending request does not pull the owner straight back to Approve.
    const polls = () => call.mock.calls.filter(([method]) => method === "hosted.requests").length;
    const before = polls();
    await waitFor(() => expect(polls()).toBeGreaterThan(before), { timeout: 6000 });
    expect(screen.getByRole("heading", { name: "Scan on your phone" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Continue to approval" }));
    fireEvent.click(await screen.findByRole("button", { name: "Review and approve" }));
    expect(screen.getByRole("button", { name: "Approve device" })).toBeDisabled();
    expect(screen.getByLabelText("Device name")).toHaveValue("");
    expect(call).not.toHaveBeenCalledWith("hosted.approve", expect.anything());
  }, 10000);
  it("only completes the wizard after successful approval and lets the dialog finish", async () => {
    let resolve!: () => void;
    const approval = new Promise<void>(done => { resolve = done; });
    const call = vi.fn((method: string) => method === "hosted.approve" ? approval : Promise.resolve(method === "hosted.root_code" ? rootCode : { requests: [offered] }));
    const onDone = vi.fn();
    render(<HostedPhoneSetup hosted={state(true).hosted!} client={client(call)} onDone={onDone} />);
    fireEvent.click(screen.getByRole("button", { name: "Continue to approval" }));
    fireEvent.click(await screen.findByRole("button", { name: "Review and approve" }));
    fireEvent.change(screen.getByLabelText("Device name"), { target: { value: "My phone" } });
    fireEvent.click(screen.getByLabelText("Every group matches my device"));
    fireEvent.click(screen.getByRole("button", { name: "Approve device" }));
    expect(screen.queryByRole("heading", { name: "Phone approved" })).toBeNull();
    await act(async () => resolve());
    expect(screen.getByRole("heading", { name: "Phone approved" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(onDone).toHaveBeenCalledOnce();
  });
  it("does not replace a reviewed device with a late manual inspection", async () => {
    let resolve!: (value: typeof offered) => void;
    const inspection = new Promise<typeof offered>(done => { resolve = done; });
    const call = vi.fn((method: string) => method === "hosted.request.inspect" ? inspection : Promise.resolve({ requests: [offered] }));
    render(<HostedApproveDevice hosted={state(true).hosted!} client={client(call)} />);
    await screen.findByRole("button", { name: "Review and approve" });
    fireEvent.click(screen.getByText("My device hasn't appeared"));
    const input = screen.getByLabelText("Device request code");
    fireEvent.change(input, { target: { value: "first" } });
    fireEvent.click(screen.getByRole("button", { name: "Check request" }));
    fireEvent.click(screen.getByRole("button", { name: "Review and approve" }));
    await act(async () => resolve({ ...offered, fingerprint: "OUTDATED SECURITY CODE" }));
    expect(screen.getByText(offered.fingerprint)).toBeVisible();
    expect(screen.queryByText("OUTDATED SECURITY CODE")).toBeNull();
    expect(screen.getByRole("button", { name: "Approve device" })).toBeDisabled();
  });
  it("keeps self-hosting explicit and routes pending invitations to their own flow", async () => {
    const bridge = client();
    const view = render(<PhoneSetup state={state()} client={bridge} />);
    expect(screen.queryByRole("button", { name: "Open server invitation" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Use my own Hub instead" }));
    expect(await screen.findByRole("button", { name: "Open server invitation" })).toBeVisible();
    expect(bridge.call).toHaveBeenCalledWith("settings.save", { setup: { mode: "hub" } });
    view.unmount();
    render(<PhoneSetup state={{ ...state(), enrollment: { ready: true, approved: false, id: "synthetic-invite" } } as State} client={bridge} />);
    expect(screen.getByRole("button", { name: "Use invitation" })).toBeVisible();
  });
  it("takes the Settings shortcut to the same Phone screen", async () => {
    const value = state();
    const call = vi.fn(async (method: string) => method === "state" ? value : {});
    render(<App providedClient={client(call)} />);
    await screen.findByRole("heading", { name: "Connect your phone" });
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    fireEvent.click(screen.getByRole("button", { name: "Connect a phone" }));
    expect(screen.getByRole("heading", { name: "Connect your phone" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Phone" })).toHaveAttribute("aria-current", "page");
  });
  it("drops the Settings shortcut once a phone is connected", async () => {
    const value = state(true);
    value.phone = { ...value.phone!, devices: [{ id: offered.device_id, name: "My phone", hosted: true, online: true, last_seen_at: null, capabilities: ["files"] }] };
    const call = vi.fn(async (method: string) => method === "state" ? value : {});
    render(<App providedClient={client(call)} />);
    await screen.findByRole("heading", { name: "My phone" });
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    expect(screen.getByRole("heading", { name: "This computer" })).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Connect your phone" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Connect a phone" })).toBeNull();
  });
});
