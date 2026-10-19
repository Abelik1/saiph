// SPDX-License-Identifier: AGPL-3.0-or-later
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DeviceChanges, HostedSettings } from "./HostedSettings";
import { chooseOption } from "../test-helpers";
import type { Client, HostedState } from "./types";
const off: HostedState = {available: true, enabled: false, configured: true, identity: false, status: "off"};
const active: HostedState = {...off, enabled: true, identity: true, status: "active", account: {status: "signed_in", refresh_tokens: false, error: ""}, roster: {expires_at: 1900000000, version: 2, clock_warning: false, members: [{id: "root", label: "This computer", root: true, fingerprint: "root fingerprint"}, {id: "phone", label: "Phone", root: false, fingerprint: "phone fingerprint"}]}};
function setup(hosted: HostedState, call = vi.fn().mockResolvedValue({})) { render(<HostedSettings hosted={hosted} client={{call} as unknown as Client} />); return call; }
describe("Hosted preview settings", () => {
  it("offers one sign-in action while off, without performing native work until clicked", async () => {
    const call = setup(off);
    expect(screen.getByRole("status")).toHaveTextContent("Off"); expect(call).not.toHaveBeenCalled();
    expect(screen.queryByText("Deployment settings")).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
    fireEvent.click(screen.getByRole("button", {name: "Continue with Google"}));
    await waitFor(() => expect(call).toHaveBeenCalledWith("hosted.sign_in", { google: true }));
    expect(call.mock.calls.map(([method]) => method)).toEqual(["hosted.enable", "hosted.sign_in"]);
  });
  it("turns Hosted back on without reopening the browser when the account is still signed in", async () => {
    const call = setup({...off, identity: true, account: {status: "signed_in", refresh_tokens: false, error: ""}});
    expect(screen.queryByText(/New to the beta/)).toBeNull();
    fireEvent.click(screen.getByRole("button", {name: "Continue with Google"}));
    await waitFor(() => expect(call).toHaveBeenCalledWith("hosted.enable", {enabled: true}));
    expect(call).not.toHaveBeenCalledWith("hosted.sign_in", { google: true });
  });
  it("says when Windows Firewall blocks Saiph on the network and opens its settings", async () => {
    const call = setup({...active, lan_notice: "Windows Firewall blocks Saiph on your network, so your phone and other computers can't connect directly."});
    expect(screen.getByRole("alert")).toHaveTextContent("Windows Firewall blocks Saiph on your network");
    fireEvent.click(screen.getByRole("button", {name: "Open firewall settings"}));
    await waitFor(() => expect(call).toHaveBeenCalledWith("hosted.firewall.open"));
  });
  it("points a new person to the free trial before signing in", () => { setup(off); expect(screen.getByText(/Start your free trial \(no card needed\)/)).toBeVisible(); });
  it("shows free trial days left with a subscribe button that opens the plans page", async () => {
    const call = setup({...active, access: {state: "trial", days_left: 3, trial_until: 1900000000, message: "Free trial: 3 days left. Subscribe on the Saiph website to keep Saiph Cloud after it ends; nothing is charged automatically."}});
    const notice = screen.getByLabelText("Saiph Cloud access");
    expect(notice).toHaveTextContent("Free trial · 3 days left");
    fireEvent.click(screen.getByRole("button", {name: "Subscribe"}));
    await waitFor(() => expect(call).toHaveBeenCalledWith("help.open", {link: "plans"}));
  });
  it("explains an ended trial once, keeps the devices list, and offers to subscribe", () => {
    const message = "Your free trial has ended. Subscribe on the Saiph website to reconnect your devices. Nothing was deleted: your devices, approvals and data are kept.";
    setup({...active, roster: null, status: "no_access", error: message, access: {state: "trial_ended", days_left: 0, trial_until: 1800000000, message}});
    expect(screen.getAllByText(/Your free trial has ended/)).toHaveLength(1);
    expect(screen.getByText("Free trial ended")).toBeVisible();
    expect(screen.getByText("Paused: no Cloud access")).toBeVisible();
    expect(screen.getByRole("button", {name: "Subscribe"})).toBeVisible();
  });
  it("shows nothing extra for subscribers and invitation holders", () => {
    setup({...active, access: {state: "active", days_left: null, trial_until: 1800000000, message: ""}});
    expect(screen.queryByLabelText("Saiph Cloud access")).toBeNull();
  });
  it("requires deployment config and respects self-hosted pairing", () => { setup({...off, configured: false, self_hosted_paired: true}); expect(screen.queryByRole("button", {name: "Turn on Cloud"})).toBeNull(); expect(screen.getByText(/paired with a self-hosted Hub/)).toBeVisible(); });
  it("requires explicit full-fingerprint confirmation before approval", async () => {
    const call = setup(active, vi.fn().mockResolvedValue({device_id: "phone", fingerprint: "FULL FINGERPRINT", expires_at: 1900000000}));
    fireEvent.change(screen.getByLabelText("Device request code"), {target: {value: "orion-approve-v1:synthetic"}}); fireEvent.click(screen.getByRole("button", {name: "Check request"}));
    await screen.findByText("FULL FINGERPRINT"); expect(screen.getByRole("button", {name: "Approve device"})).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Device name"), {target: {value: "My phone"}}); fireEvent.click(screen.getByLabelText("Every group matches my device")); fireEvent.click(screen.getByRole("button", {name: "Approve device"}));
    await waitFor(() => expect(call).toHaveBeenCalledWith("hosted.approve", {code: "orion-approve-v1:synthetic", label: "My phone", confirmed: true}));
  });
  it("drops confirmation when the owner rejects or replaces a request", async () => {
    setup(active, vi.fn().mockResolvedValue({device_id: "phone", fingerprint: "fingerprint", expires_at: 1900000000}));
    fireEvent.change(screen.getByLabelText("Device request code"), {target: {value: "first"}}); fireEvent.click(screen.getByRole("button", {name: "Check request"})); await screen.findByText(/Compare every group/);
    fireEvent.click(screen.getByLabelText("Every group matches my device")); fireEvent.click(screen.getByRole("button", {name: "Not this device"})); expect(screen.queryByRole("button", {name: "Approve device"})).toBeNull();
    fireEvent.change(screen.getByLabelText("Device request code"), {target: {value: "different"}}); fireEvent.click(screen.getByRole("button", {name: "Check request"})); await screen.findByText(/Compare every group/); expect(screen.getByLabelText("Every group matches my device")).not.toBeChecked();
  });
  it("shows a device that offered its request and approves it only after the full fingerprint is confirmed", async () => {
    const offered = {code: "orion-approve-v1:synthetic", device_id: "dev_phone", fingerprint: "ABCD 1234 EF56 7890", expires_at: 1900000000};
    const call = setup(active, vi.fn(async (method: string) => method === "hosted.requests" ? {requests: [offered]} : {}));
    fireEvent.click(await screen.findByRole("button", {name: "Review and approve"}));
    expect(screen.getByText("ABCD 1234 EF56 7890")).toBeVisible();
    fireEvent.change(screen.getByLabelText("Device name"), {target: {value: "My phone"}});
    expect(screen.getByRole("button", {name: "Approve device"})).toBeDisabled();
    fireEvent.click(screen.getByLabelText("Every group matches my device"));
    fireEvent.click(screen.getByRole("button", {name: "Approve device"}));
    await waitFor(() => expect(call).toHaveBeenCalledWith("hosted.approve", {code: offered.code, label: "My phone", confirmed: true}));
  });
  it("says whether Windows Hello protects device changes and lists recent changes", () => {
    setup({...active, user_verification: "windows_hello", security_events: [{id: "e1", kind: "added", device_id: "phone", label: "Phone", at: 1900000000}]});
    expect(screen.getByText(/Windows Hello confirms it's you/)).toBeVisible();
    expect(screen.getByText(/Approved Phone/)).toBeInTheDocument();
  });
  it("asks the owner to set up verification when none is available", () => {
    setup({...active, user_verification: "unavailable"});
    expect(screen.getByText(/Anyone using this computer while it is unlocked can add a device/)).toBeVisible();
  });
  it("requires explicit retirement confirmation and does not show data while signed out", () => { setup({...active, enabled: false}); expect(screen.getByRole("button", {name: "Forget Cloud on this computer"})).toBeDisabled(); expect(screen.queryByRole("button", {name: "Choose file to send"})).toBeNull(); });
  it("lists recent device changes in a design-system disclosure, newest first, with a count and relative times", () => {
    const now = 1900000000 * 1000;
    render(<DeviceChanges now={now} events={[
      {id: "e1", kind: "added", device_id: "phone", label: "Phone", at: 1900000000 - 7200},
      {id: "e2", kind: "removed", device_id: "old", label: "Old laptop", at: 1900000000 - 120},
    ]} />);
    const summary = screen.getByText("Recent device changes", {selector: "summary span"}).closest("summary")!;
    expect(summary.parentElement).toHaveAttribute("data-slot", "disclosure");
    expect(summary.parentElement).not.toHaveAttribute("open");
    expect(summary).toHaveTextContent("2");
    fireEvent.click(summary);
    const rows = screen.getAllByRole("listitem");
    expect(rows.map(row => row.textContent)).toEqual(["Removed Old laptop2 min ago", "Approved Phone2 h ago"]);
  });
  it("previews the latest Cloud notification as a card and dismisses it", async () => {
    const call = setup({...active, notifications: [
      {id: "n1", device_id: "phone", app: "Synthetic app", title: "Older", text: "Older body", timestamp: 1000},
      {id: "n2", device_id: "phone", app: "Synthetic app", title: "Newest", text: "Newest body", timestamp: 2000},
    ]});
    const preview = screen.getByRole("group", {name: "Latest phone notification"});
    expect(preview).toHaveTextContent("Newest body");
    expect(preview).not.toHaveTextContent("Older body");
    expect(preview).toHaveTextContent("1 more notification on the Phone page.");
    fireEvent.click(screen.getByRole("button", {name: "Dismiss Newest"}));
    await waitFor(() => expect(call).toHaveBeenCalledWith("hosted.notification.dismiss", {id: "n2"}));
  });
  it("chooses where to send a file from a design-system select", async () => {
    const call = setup(active);
    expect(screen.getByRole("button", {name: "Choose file to send"})).toBeDisabled();
    chooseOption("Send file to", "Phone · Device");
    fireEvent.click(screen.getByRole("button", {name: "Choose file to send"}));
    await waitFor(() => expect(call).toHaveBeenCalledWith("hosted.file.choose", {target: "phone"}));
  });
});
