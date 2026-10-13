// SPDX-License-Identifier: AGPL-3.0-or-later
import { act, render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { Phone } from "./Phone";
import type { Client, State } from "./types";

function state(online = true): State {
  return { hub_inbox: { items: [], synced_at: null, error: "" }, phone: {
    status: "Online", error: "", devices: [{ id: "phone", name: "Galaxy A55", online, last_seen_at: null, capabilities: ["battery", "notifications"], battery: { battery_level: 76, is_charging: false, updated_at: 1 } }],
    notifications: [{ id: "n", device_id: "phone", key: "private-key", app: "Messages", package: "test", title: "Synthetic message", text: "Synthetic body", timestamp: 1, actions: [{ index: 2, label: "Archive" }], reply_key: "reply" }],
  } } as unknown as State;
}
describe("Phone page", () => {
  it("names the device that turned on shared Do Not Disturb and toggles it everywhere", async () => {
    const call = vi.fn().mockResolvedValue({ active: false, shared: true });
    const fixture = { ...state(), settings: { hub: { paired: true, device_id: "desktop", base_url: "" }, link: { camera: { enabled: false } } },
      dnd: { enabled: true, active: true, source: "phone", changed_at: 1, quiet: true } } as unknown as State;
    render(<Phone state={fixture} client={{ call, subscribe: () => () => {} } as Client} />);
    expect(screen.getByText("On · from Galaxy A55")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Turn off Do Not Disturb on all devices" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("continuity.dnd", { active: false }));
  });
  it("hides Do Not Disturb when sync is switched off", () => {
    const fixture = { ...state(), settings: { hub: { paired: true, device_id: "desktop", base_url: "" }, link: { camera: { enabled: false } } },
      dnd: { enabled: false, active: false, source: "", changed_at: null, quiet: false } } as unknown as State;
    render(<Phone state={fixture} client={{ call: vi.fn(), subscribe: () => () => {} } as Client} />);
    expect(screen.queryByRole("group", { name: "Do Not Disturb" })).toBeNull();
  });
  it('keeps the active microphone visible and names its actual phone while changing the selection',()=>{
    const fixture={...state(),settings:{link:{camera:{enabled:false},microphone:{enabled:false}}},microphone:{available:true,running:true,muted:false,verified:false,mode:'linux-pulse',device_id:'phone',message:'Capturing'}} as State;
    fixture.phone!.devices.push({...fixture.phone!.devices[0],id:'second-phone',name:'Second phone'});
    render(<Phone state={fixture} client={{call:vi.fn(),subscribe:()=>()=>{}} as Client}/>);
    fireEvent.change(screen.getByLabelText('Phone'),{target:{value:'second-phone'}});
    expect(screen.getByText('Galaxy A55 microphone · Capturing audio')).toBeVisible();
    expect(screen.getByRole('button',{name:'Stop phone microphone'})).toBeEnabled();
  });
  it('offers an enabled camera in Link without installing personal Workspace',()=>{
    const fixture={...state(),settings:{link:{camera:{enabled:true}}},modules:{workspace:{installed:false,enabled:false}},camera:{available:true,running:false,verified:false,mode:'linux-v4l2',device_id:null,message:'Ready'}} as State;
    render(<Phone state={fixture} client={{call:vi.fn(),subscribe:()=>()=>{}} as Client}/>);
    expect(screen.getByRole('button',{name:'Use phone as webcam'})).toBeEnabled();
  });
  it("shows real state and sends explicit replies/actions to the owning notification", async () => {
    const call = vi.fn().mockResolvedValue({ queued: true });
    render(<Phone state={state()} client={{ call, subscribe: () => () => {} } as Client} />);
    expect(screen.getByText("76%")).toBeVisible();
    expect(screen.queryByRole("button", { name: /Connect|Refresh|Sync/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Archive" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("phone.notification", { id: "n", operation: "action", index: 2 }));
    fireEvent.change(screen.getByLabelText("Reply to Synthetic message"), { target: { value: "Synthetic reply" } });
    fireEvent.click(screen.getByRole("button", { name: "Send reply" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("phone.notification", { id: "n", operation: "reply", text: "Synthetic reply", reply_key: "reply" }));
    expect(screen.getByText("Synthetic message")).toBeVisible(); // Phone remains the authority; no optimistic deletion.
  });
  it("retains offline content while preventing remote actions", () => {
    render(<Phone state={state(false)} client={{ call: vi.fn(), subscribe: () => () => {} } as Client} />);
    expect(screen.getByText("Offline")).toBeVisible();
    expect(screen.getByRole("button", { name: "Archive" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Send reply" })).toBeDisabled();
    expect(screen.getByText("Synthetic body")).toBeVisible();
  });
});

describe("Phone pairing invitations", () => {
  const qr = {
    modules: Array.from({ length: 29 }, () => "0".repeat(29)),
    expires_at: "2026-01-01T12:10:00Z", expires_in: 600,
  };
  function pairedState(): State {
    return { ...state(), settings: { hub: { paired: true }, link: { camera: { enabled: false } } } } as State;
  }
  function clientFor(call = vi.fn().mockResolvedValue(qr)): Client {
    return { call, subscribe: () => () => {} } as Client;
  }

  it("offers pairing only on a paired computer and keeps the invitation file option", async () => {
    const call = vi.fn().mockResolvedValue({});
    const client = clientFor(call);
    const { rerender } = render(<Phone state={state()} client={client} />);
    expect(screen.queryByRole("group", { name: "Add a device" })).toBeNull();
    rerender(<Phone state={pairedState()} client={client} />);
    fireEvent.click(screen.getByRole("button", { name: "Save invitation file" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("enrollment.export"));
    expect(screen.queryByRole("img", { name: "Pairing QR code" })).toBeNull();
  });

  it("shows a QR on request, prevents another while visible, and allows closing it", async () => {
    const call = vi.fn().mockResolvedValue(qr);
    render(<Phone state={pairedState()} client={clientFor(call)} />);
    fireEvent.click(screen.getByRole("button", { name: "Show pairing QR" }));
    expect(await screen.findByRole("img", { name: "Pairing QR code" })).toBeVisible();
    expect(call).toHaveBeenCalledExactlyOnceWith("enrollment.qr");
    expect(screen.getByRole("button", { name: "Show pairing QR" })).toBeDisabled();
    expect(screen.getByRole("timer")).toHaveTextContent("Expires in 10:00");
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("img", { name: "Pairing QR code" })).toBeNull();
    expect(screen.getByRole("button", { name: "Show pairing QR" })).toBeEnabled();
  });

  it("closes on admission of a new device without closing on ordinary status updates", async () => {
    const client = clientFor();
    const initial = pairedState();
    const { rerender } = render(<Phone state={initial} client={client} />);
    fireEvent.click(screen.getByRole("button", { name: "Show pairing QR" }));
    await screen.findByRole("img", { name: "Pairing QR code" });
    rerender(<Phone state={{ ...initial, phone: { ...initial.phone!, status: "Updated" } }} client={client} />);
    expect(screen.getByRole("img", { name: "Pairing QR code" })).toBeVisible();
    const admitted = { ...initial, phone: { ...initial.phone!, devices: [...initial.phone!.devices,
      { ...initial.phone!.devices[0], id: "new-phone", name: "New test phone" }] } };
    rerender(<Phone state={admitted} client={client} />);
    expect(screen.queryByRole("img", { name: "Pairing QR code" })).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent("Your new device was added");
  });

  it("removes an expired QR and allows a fresh request", async () => {
    vi.useFakeTimers();
    try {
      const client = clientFor(vi.fn().mockResolvedValue({ ...qr, expires_in: 1 }));
      render(<Phone state={pairedState()} client={client} />);
      await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Show pairing QR" })); });
      expect(screen.getByRole("img", { name: "Pairing QR code" })).toBeVisible();
      act(() => vi.advanceTimersByTime(1000));
      expect(screen.queryByRole("img", { name: "Pairing QR code" })).toBeNull();
    } finally { vi.useRealTimers(); }
    expect(screen.getByRole("status")).toHaveTextContent("pairing QR expired");
    expect(screen.getByRole("button", { name: "Show pairing QR" })).toBeEnabled();
  });

  it("rejects a malformed response and leaves the file alternative available", async () => {
    render(<Phone state={pairedState()} client={clientFor(vi.fn().mockResolvedValue({ ...qr, modules: ["invalid"] }))} />);
    fireEvent.click(screen.getByRole("button", { name: "Show pairing QR" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Save an invitation file instead");
    expect(screen.queryByRole("img", { name: "Pairing QR code" })).toBeNull();
    expect(screen.getByRole("button", { name: "Save invitation file" })).toBeEnabled();
  });

  it("discards the QR when leaving the Phone page", async () => {
    const client = clientFor();
    const { unmount } = render(<Phone state={pairedState()} client={client} />);
    fireEvent.click(screen.getByRole("button", { name: "Show pairing QR" }));
    await screen.findByRole("img", { name: "Pairing QR code" });
    unmount();
    render(<Phone state={pairedState()} client={client} />);
    expect(screen.queryByRole("img", { name: "Pairing QR code" })).toBeNull();
    expect(screen.getByRole("button", { name: "Show pairing QR" })).toBeEnabled();
  });
  it("clears the QR when initially unavailable device state arrives", async () => {
    const client = clientFor();
    const initial = { ...pairedState(), phone: undefined };
    const { rerender } = render(<Phone state={initial} client={client} />);
    fireEvent.click(screen.getByRole("button", { name: "Show pairing QR" }));
    await screen.findByRole("img", { name: "Pairing QR code" });
    rerender(<Phone state={pairedState()} client={client} />);
    expect(screen.queryByRole("img", { name: "Pairing QR code" })).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent("device list changed");
  });

  it.each(["unpair", "switch"])("clears the QR on a Hub %s", async (change) => {
    const client = clientFor();
    const initial = pairedState();
    const { rerender } = render(<Phone state={initial} client={client} />);
    fireEvent.click(screen.getByRole("button", { name: "Show pairing QR" }));
    await screen.findByRole("img", { name: "Pairing QR code" });
    const changed = { ...initial, settings: { ...initial.settings!, hub: {
      ...initial.settings!.hub, paired: change !== "unpair", base_url: "http://100.64.0.2:8765",
    } } };
    rerender(<Phone state={changed} client={client} />);
    expect(screen.queryByRole("img", { name: "Pairing QR code" })).toBeNull();
  });

  it.each(["unmount", "switch"])("discards a pending QR response after %s", async (change) => {
    let resolve!: (value: typeof qr) => void;
    const call = vi.fn().mockReturnValue(new Promise<typeof qr>((done) => { resolve = done; }));
    const client = clientFor(call);
    const initial = pairedState();
    const { rerender, unmount } = render(<Phone state={initial} client={client} />);
    fireEvent.click(screen.getByRole("button", { name: "Show pairing QR" }));
    expect(screen.getByRole("button", { name: "Show pairing QR" })).toBeDisabled();
    if (change === "unmount") unmount();
    else rerender(<Phone state={{ ...initial, settings: { ...initial.settings!, hub: {
      ...initial.settings!.hub, base_url: "http://100.64.0.2:8765",
    } } }} client={client} />);
    await act(async () => { resolve(qr); });
    expect(screen.queryByRole("img", { name: "Pairing QR code" })).toBeNull();
  });

  it("counts request delay against the invitation lifetime", async () => {
    vi.useFakeTimers();
    try {
      vi.setSystemTime(new Date("2026-01-01T12:00:00Z"));
      let resolve!: (value: typeof qr) => void;
      const client = clientFor(vi.fn().mockReturnValue(new Promise<typeof qr>((done) => { resolve = done; })));
      render(<Phone state={pairedState()} client={client} />);
      fireEvent.click(screen.getByRole("button", { name: "Show pairing QR" }));
      vi.setSystemTime(new Date("2026-01-01T12:00:10Z"));
      await act(async () => { resolve(qr); });
      expect(screen.getByRole("timer")).toHaveTextContent("Expires in 9:50");
    } finally { vi.useRealTimers(); }
  });

});
