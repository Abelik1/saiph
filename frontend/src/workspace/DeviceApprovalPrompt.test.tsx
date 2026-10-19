// SPDX-License-Identifier: AGPL-3.0-or-later
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DeviceApprovalPrompt } from "./DeviceApprovalPrompt";
import { useWizardOpen } from "./pairingWizard";
import type { Client, HostedState } from "./types";

const hosted = { available: true, enabled: true, status: "active", identity: true, role: "root", fingerprint: "MAIN FULL" } as HostedState;
const pending = { code: "orion-approve-v1:synthetic", device_id: "dev_new", fingerprint: "NEW FULL", expires_at: Date.now() / 1000 + 240, location: null };
const approvals = (extra = {}) => ({ requests: [pending], waiting: 1, flood: false, ...extra });
const bridge = (call: ReturnType<typeof vi.fn>) => ({ call } as unknown as Client);

describe("Approving a new device on the main computer", () => {
  it("warns about an unknown device and approves only after comparison and a name", async () => {
    const call = vi.fn(async (method: string) => method === "hosted.approvals" ? approvals() : { approved: "dev_new" });
    render(<DeviceApprovalPrompt hosted={hosted} client={bridge(call)} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("This is an unknown device at an unknown location. Are you sure you want to approve this device?");
    expect(screen.getByLabelText("New device's security code")).toHaveTextContent("NEW FULL");
    expect(screen.getByLabelText("This computer's security code")).toHaveTextContent("MAIN FULL");
    const approve = screen.getByRole("button", { name: "Approve" });
    expect(approve).toBeDisabled();
    fireEvent.click(screen.getByLabelText("Every group matches the new device, and I started this"));
    expect(approve).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Name this device"), { target: { value: "Laptop" } });
    fireEvent.click(approve);
    await waitFor(() => expect(call).toHaveBeenCalledWith("hosted.approve", { code: pending.code, label: "Laptop", confirmed: true }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
  it("labels a reported location approximate and warns when many devices ask", async () => {
    const call = vi.fn(async () => approvals({ requests: [{ ...pending, location: "Lisbon, PT" }], waiting: 4, flood: true }));
    render(<DeviceApprovalPrompt hosted={hosted} client={bridge(call)} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("near Lisbon, PT (approximate)");
    expect(screen.getByText(/Several devices asked to join/)).toBeVisible();
    expect(screen.getByRole("timer")).toHaveTextContent("3 more waiting");
  });
  it("denies or blocks without approving", async () => {
    for (const [button, method] of [["Deny", "hosted.request.deny"], ["Block this device", "hosted.request.block"]]) {
      const call = vi.fn(async (name: string) => name === "hosted.approvals" ? approvals() : {});
      const { unmount } = render(<DeviceApprovalPrompt hosted={hosted} client={bridge(call)} />);
      fireEvent.click(await screen.findByRole("button", { name: button }));
      await waitFor(() => expect(call).toHaveBeenCalledWith(method, { device_id: "dev_new" }));
      expect(call).not.toHaveBeenCalledWith("hosted.approve", expect.anything());
      unmount();
    }
  });
  it("stays quiet on joined computers, while a connection wizard is open and for expired requests", async () => {
    const call = vi.fn(async () => approvals());
    const member = render(<DeviceApprovalPrompt hosted={{ ...hosted, role: "member" }} client={bridge(call)} />);
    expect(call).not.toHaveBeenCalled();
    member.unmount();
    function Wizard() { useWizardOpen(); return null; }
    const wizard = render(<><Wizard /><DeviceApprovalPrompt hosted={hosted} client={bridge(call)} /></>);
    expect(call).not.toHaveBeenCalled();
    wizard.unmount();
    const expired = vi.fn(async () => approvals({ requests: [{ ...pending, expires_at: 1 }] }));
    render(<DeviceApprovalPrompt hosted={hosted} client={bridge(expired)} />);
    await waitFor(() => expect(expired).toHaveBeenCalledWith("hosted.approvals"));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
