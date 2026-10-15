// SPDX-License-Identifier: AGPL-3.0-or-later
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { HostedJoin } from "./HostedJoin";
import { HostedSettings } from "./HostedSettings";
import type { Client, HostedState } from "./types";

const client = (call: ReturnType<typeof vi.fn>) => ({ call } as unknown as Client);
const request = { code: "orion-approve-v1:synthetic", fingerprint: "AAAA BBBB", root_fingerprint: "ROOT FULL", expires_in: 300 };

describe("Joining Saiph Hosted as another computer", () => {
  it("checks the main computer's code, needs the fingerprint confirmed, then shows the request code", async () => {
    const call = vi.fn(async (method: string) =>
      method === "hosted.join.inspect" ? { device_id: "dev_main", fingerprint: "ROOT FULL" } : request);
    render(<HostedJoin client={client(call)} waiting={false} />);
    fireEvent.change(screen.getByLabelText("Main computer's code"), { target: { value: " orion-root-v1:synthetic " } });
    fireEvent.click(screen.getByRole("button", { name: "Check code" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("hosted.join.inspect", { code: "orion-root-v1:synthetic" }));
    expect(await screen.findByText("ROOT FULL")).toBeVisible();
    const join = screen.getByRole("button", { name: "Join as another computer" });
    expect(join).toBeDisabled();
    fireEvent.click(screen.getByLabelText("The whole fingerprint matches my main computer"));
    fireEvent.click(join);
    await waitFor(() => expect(call).toHaveBeenCalledWith("hosted.join", { code: "orion-root-v1:synthetic", confirmed: true }));
    expect(await screen.findByLabelText("Request code for your main computer")).toHaveValue("orion-approve-v1:synthetic");
    expect(screen.getByText("AAAA BBBB")).toBeVisible();
  });
  it("editing the code withdraws an earlier confirmation", async () => {
    const call = vi.fn(async () => ({ device_id: "dev_main", fingerprint: "ROOT FULL" }));
    render(<HostedJoin client={client(call)} waiting={false} />);
    fireEvent.change(screen.getByLabelText("Main computer's code"), { target: { value: "first" } });
    fireEvent.click(screen.getByRole("button", { name: "Check code" }));
    fireEvent.click(await screen.findByLabelText("The whole fingerprint matches my main computer"));
    fireEvent.change(screen.getByLabelText("Main computer's code"), { target: { value: "different" } });
    expect(screen.queryByRole("button", { name: "Join as another computer" })).toBeNull();
    expect(call).not.toHaveBeenCalledWith("hosted.join", expect.anything());
  });
  it("lets a waiting computer show a fresh request code", async () => {
    const call = vi.fn(async () => request);
    render(<HostedJoin client={client(call)} waiting />);
    fireEvent.click(screen.getByRole("button", { name: "Show request code" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("hosted.join.request"));
    expect(await screen.findByRole("button", { name: "Show a new request code" })).toBeVisible();
  });
});

describe("Hosted settings on a joined computer", () => {
  const member: HostedState = {
    available: true, enabled: true, status: "active", identity: true, configured: true, role: "member",
    fingerprint: "SELF FULL", root_fingerprint: "ROOT FULL",
    account: { status: "signed_in", error: "", refresh_tokens: false },
    roster: { expires_at: 2_000_000_000, version: 3, clock_warning: false, members: [
      { id: "dev_main", label: "Main computer", root: true, self: false, fingerprint: "ROOT FULL" },
      { id: "dev_self", label: "This computer", root: false, self: true, fingerprint: "SELF FULL" },
    ] },
  };
  it("hides approving and removing devices, and can still send to the main computer", () => {
    render(<HostedSettings hosted={member} client={client(vi.fn())} />);
    expect(screen.queryByLabelText("Device request code")).toBeNull();
    expect(screen.queryByRole("button", { name: /Revoke/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Show root approval code" })).toBeNull();
    expect(screen.getByText(/joined your account as another computer/)).not.toBeVisible();
    fireEvent.click(screen.getByText("Connection details"));
    expect(screen.getByText(/joined your account as another computer/)).toBeVisible();
    expect(screen.getByRole("option", { name: "Main computer" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "This computer" })).toBeNull();
  });
  it("offers joining only before this computer has an identity", () => {
    const fresh: HostedState = { ...member, identity: false, role: null, roster: null, status: "setup" };
    render(<HostedSettings hosted={fresh} client={client(vi.fn())} />);
    expect(screen.getByText("Join as another computer")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Set up this computer" })).toBeVisible();
  });
  it("shows the waiting state while the main computer has not approved yet", () => {
    render(<HostedSettings hosted={{ ...member, status: "awaiting_approval", roster: null }} client={client(vi.fn())} />);
    expect(screen.getByRole("status")).toHaveTextContent("Waiting for your main computer to approve this computer");
    expect(screen.getByRole("button", { name: "Show request code" })).toBeVisible();
  });
});
