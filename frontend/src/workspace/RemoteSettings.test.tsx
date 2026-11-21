// SPDX-License-Identifier: AGPL-3.0-or-later
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RemoteSettings } from "./RemoteSettings";
import type { Client, RemoteStatus, State } from "./types";

const remote: RemoteStatus = { enabled: false, devices: [], wayland: false, last: null, adapters: {
  media: { name: "Media", enabled: true, available: true }, system: { name: "This computer", enabled: false, available: true },
  keyboard: { name: "Type into the focused app", enabled: false, available: true } } };
const state = { settings: { hub: { device_id: "desktop", paired: true, base_url: "" } }, phone: { status: "", error: "", notifications: [],
  devices: [{ id: "desktop", name: "Desktop", online: true, last_seen_at: null, capabilities: [] }, { id: "phone", name: "Galaxy A55", online: true, last_seen_at: null, capabilities: ["battery"] }] } } as unknown as State;

describe("Phone remote settings", () => {
  it("stays off until enabled and saves chosen phones and apps", async () => {
    const call = vi.fn().mockResolvedValue({});
    render(<RemoteSettings remote={remote} state={state} client={{ call } as unknown as Client} />);
    expect(screen.getByLabelText("Galaxy A55")).toBeDisabled();
    expect(screen.queryByLabelText("Desktop")).toBeNull();
    expect(screen.getByText(/type into whichever app is in front/)).toBeVisible();
    fireEvent.click(screen.getByLabelText("Allow phone remote control"));
    fireEvent.click(screen.getByLabelText("Galaxy A55"));
    fireEvent.click(screen.getByLabelText(/This computer/));
    fireEvent.click(screen.getByRole("button", { name: "Save remote preferences" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("settings.save", { link: { remote: { enabled: true, devices: ["phone"], adapters: { media: true, system: true, keyboard: false } } } }));
  });
  it("lists Saiph Cloud phones too, but never this computer or other computers", () => {
    const cloud = { ...state, phone: undefined, hosted: { roster: { members: [
      { id: "cloud-phone", label: "Pixel 8", root: false, kind: "phone", fingerprint: "" },
      { id: "laptop", label: "Laptop", root: true, kind: "computer", fingerprint: "" },
      { id: "self", label: "This computer", root: false, self: true, kind: "computer", fingerprint: "" }] } } } as unknown as State;
    render(<RemoteSettings remote={remote} state={cloud} client={{ call: vi.fn() } as unknown as Client} />);
    expect(screen.getByLabelText("Pixel 8")).toBeInTheDocument();
    expect(screen.queryByLabelText("Laptop")).toBeNull();
    expect(screen.queryByLabelText("This computer")).toBeNull();
  });
  it("lists a phone once when the Phone page and the Cloud roster both have it", () => {
    const both = { ...state, hosted: { roster: { members: [
      { id: "phone", label: "Galaxy A55", root: false, kind: "phone", fingerprint: "" },
      { id: "cloud-phone", label: "Pixel 8", root: false, kind: "phone", fingerprint: "" }] } } } as unknown as State;
    render(<RemoteSettings remote={remote} state={both} client={{ call: vi.fn() } as unknown as Client} />);
    expect(screen.getAllByLabelText("Galaxy A55")).toHaveLength(1);
    expect(screen.getAllByLabelText("Pixel 8")).toHaveLength(1);
  });
  it("explains Wayland limits", () => {
    render(<RemoteSettings remote={{ ...remote, wayland: true }} state={state} client={{ call: vi.fn() } as unknown as Client} />);
    expect(screen.getByText(/Wayland does not let apps send keys/)).toBeVisible();
  });
});
