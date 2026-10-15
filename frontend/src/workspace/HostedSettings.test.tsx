// SPDX-License-Identifier: AGPL-3.0-or-later
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { HostedSettings } from "./HostedSettings";
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
    fireEvent.click(screen.getByRole("button", {name: "Sign in to Saiph"}));
    await waitFor(() => expect(call).toHaveBeenCalledWith("hosted.sign_in"));
    expect(call.mock.calls.map(([method]) => method)).toEqual(["hosted.enable", "hosted.sign_in"]);
  });
  it("turns Hosted back on without reopening the browser when the account is still signed in", async () => {
    const call = setup({...off, identity: true, account: {status: "signed_in", refresh_tokens: false, error: ""}});
    expect(screen.queryByText(/New to the beta/)).toBeNull();
    fireEvent.click(screen.getByRole("button", {name: "Sign in to Saiph"}));
    await waitFor(() => expect(call).toHaveBeenCalledWith("hosted.enable", {enabled: true}));
    expect(call).not.toHaveBeenCalledWith("hosted.sign_in");
  });
  it("points a new tester to their invitation before signing in", () => { setup(off); expect(screen.getByText(/Activate your invitation code/)).toBeVisible(); });
  it("requires deployment config and respects self-hosted pairing", () => { setup({...off, configured: false, self_hosted_paired: true}); expect(screen.queryByRole("button", {name: "Turn on Hosted"})).toBeNull(); expect(screen.getByText(/paired with a self-hosted Hub/)).toBeVisible(); });
  it("requires explicit full-fingerprint confirmation before approval", async () => {
    const call = setup(active, vi.fn().mockResolvedValue({device_id: "phone", fingerprint: "FULL FINGERPRINT", expires_at: 1900000000}));
    fireEvent.change(screen.getByLabelText("Device request code"), {target: {value: "orion-approve-v1:synthetic"}}); fireEvent.click(screen.getByRole("button", {name: "Check request"}));
    await screen.findByText("FULL FINGERPRINT"); expect(screen.getByRole("button", {name: "Approve device"})).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Device name"), {target: {value: "My phone"}}); fireEvent.click(screen.getByLabelText("The full fingerprint matches the device")); fireEvent.click(screen.getByRole("button", {name: "Approve device"}));
    await waitFor(() => expect(call).toHaveBeenCalledWith("hosted.approve", {code: "orion-approve-v1:synthetic", label: "My phone", confirmed: true}));
  });
  it("invalidates confirmation whenever request code changes", async () => {
    setup(active, vi.fn().mockResolvedValue({device_id: "phone", fingerprint: "fingerprint", expires_at: 1900000000}));
    fireEvent.change(screen.getByLabelText("Device request code"), {target: {value: "first"}}); fireEvent.click(screen.getByRole("button", {name: "Check request"})); await screen.findByText("Compare this full fingerprint with the device you are adding:");
    fireEvent.click(screen.getByLabelText("The full fingerprint matches the device")); fireEvent.change(screen.getByLabelText("Device request code"), {target: {value: "different"}}); expect(screen.queryByRole("button", {name: "Approve device"})).toBeNull();
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
  it("requires explicit retirement confirmation and does not show data while signed out", () => { setup({...active, enabled: false}); expect(screen.getByRole("button", {name: "Forget Hosted on this computer"})).toBeDisabled(); expect(screen.queryByRole("button", {name: "Choose file to send"})).toBeNull(); });
});
