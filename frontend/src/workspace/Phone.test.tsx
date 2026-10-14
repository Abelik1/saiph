// SPDX-License-Identifier: AGPL-3.0-or-later
import { act, render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { Phone } from "./Phone";
import type { Client, State } from "./types";
import { chooseMenuItem } from "../test-helpers";

function state(online = true): State {
  return {
    hub_inbox: { items: [], synced_at: null, error: "" },
    phone: {
      status: "Online",
      error: "",
      devices: [
        {
          id: "phone",
          name: "Galaxy A55",
          online,
          last_seen_at: null,
          capabilities: ["battery", "notifications"],
          battery: { battery_level: 76, is_charging: false, updated_at: 1 },
        },
      ],
      notifications: [
        {
          id: "n",
          device_id: "phone",
          key: "private-key",
          app: "Messages",
          package: "test",
          title: "Synthetic message",
          text: "Synthetic body",
          timestamp: 1,
          actions: [{ index: 2, label: "Archive" }],
          reply_key: "reply",
        },
      ],
    },
  } as unknown as State;
}
describe("Phone page", () => {
  it("shows server invitations only to people who chose to self-host", () => {
    const unpaired = { ...state(), settings: { hub: { paired: false } }, enrollment: { ready: false, id: null, expires_at: null, custom_mesh: false } };
    const client = { call: vi.fn() } as unknown as Client;
    const view = render(<Phone state={{ ...unpaired, setup: { mode: "hosted" } } as unknown as State} client={client} />);
    expect(screen.queryByRole("button", { name: "Open server invitation" })).toBeNull();
    view.rerender(<Phone state={{ ...unpaired, setup: { mode: "hub" } } as unknown as State} client={client} />);
    expect(screen.getByRole("button", { name: "Open server invitation" })).toBeVisible();
  });
  it("explains when a connected phone is not sharing its clipboard", () => {
    const client = { call: vi.fn(), subscribe: () => () => {} } as unknown as Client;
    const notice = /Clipboard isn't shared with Galaxy A55 yet/;
    const { rerender } = render(<Phone state={state()} client={client} />);
    expect(screen.getByText(notice)).toBeVisible();
    const sharing = state();
    sharing.phone!.devices[0].capabilities.push("clipboard");
    rerender(<Phone state={sharing} client={client} />);
    expect(screen.queryByText(notice)).toBeNull();
    // Switched off on this computer, or the phone is offline: nothing to fix.
    rerender(<Phone state={{ ...state(), settings: { link: { clipboard: false } } } as unknown as State} client={client} />);
    expect(screen.queryByText(notice)).toBeNull();
    rerender(<Phone state={state(false)} client={client} />);
    expect(screen.queryByText(notice)).toBeNull();
  });
  it("rings a phone that supports it", async () => {
    const call = vi.fn().mockResolvedValue({ queued: true });
    const fixture = state();
    fixture.phone!.devices[0].capabilities.push("ring");
    render(<Phone state={fixture} client={{ call, subscribe: () => () => {} } as Client} />);
    fireEvent.click(screen.getByRole("button", { name: "Find phone" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("phone.ring", { device_id: "phone" }));
  });
  it("copies a verification code from a phone notification, even offline", async () => {
    const call = vi.fn().mockResolvedValue({ copied: true });
    const fixture = state(false);
    fixture.phone!.notifications[0] = { ...fixture.phone!.notifications[0], text: "Your code is 918273", code: "918273" };
    render(<Phone state={fixture} client={{ call, subscribe: () => () => {} } as Client} />);
    fireEvent.click(screen.getByRole("button", { name: "Copy code 918273" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("phone.code.copy", { id: "n" }));
  });
  it("names the device that turned on shared Do Not Disturb and toggles it everywhere", async () => {
    const call = vi.fn().mockResolvedValue({ active: false, shared: true });
    const fixture = { ...state(), settings: { hub: { paired: true, device_id: "desktop", base_url: "" }, link: { camera: { enabled: false } } },
      dnd: { enabled: true, active: true, source: "phone", changed_at: 1, quiet: true } } as unknown as State;
    render(<Phone state={fixture} client={{ call, subscribe: () => () => {} } as Client} />);
    expect(screen.getByText("On · from Galaxy A55")).toBeVisible();
    const toggle = screen.getByRole("switch", { name: "Do Not Disturb on all devices" });
    expect(toggle).toBeChecked();
    fireEvent.click(toggle);
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
    chooseMenuItem(/^Device:/, /Second phone/);
    expect(screen.getByText('Galaxy A55 microphone · Capturing audio')).toBeVisible();
    expect(screen.getByRole('button',{name:'Stop phone microphone'})).toBeEnabled();
  });
  it("offers an enabled camera in Link without installing personal Workspace", () => {
    const fixture = {
      ...state(),
      settings: { link: { camera: { enabled: true } } },
      modules: { workspace: { installed: false, enabled: false } },
      camera: {
        available: true,
        running: false,
        verified: false,
        mode: "linux-v4l2",
        device_id: null,
        message: "Ready",
      },
    } as State;
    render(
      <Phone
        state={fixture}
        client={{ call: vi.fn(), subscribe: () => () => {} } as Client}
      />,
    );
    // An idle webcam waits in the device bar; its panel opens beside the button.
    fireEvent.click(screen.getByRole("button", { name: "Webcam" }));
    expect(
      screen.getByRole("button", { name: "Use phone as webcam" }),
    ).toBeEnabled();
  });
  it("shows real state and sends explicit replies/actions to the owning notification", async () => {
    const call = vi.fn().mockResolvedValue({ queued: true });
    render(
      <Phone
        state={state()}
        client={{ call, subscribe: () => () => {} } as Client}
      />,
    );
    expect(screen.getByText("76%")).toBeVisible();
    expect(
      screen.queryByRole("button", { name: /Connect|Refresh|Sync/ }),
    ).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Archive" }));
    await waitFor(() =>
      expect(call).toHaveBeenCalledWith("phone.notification", {
        id: "n",
        operation: "action",
        index: 2,
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Reply" }));
    fireEvent.change(screen.getByLabelText("Reply to Synthetic message"), {
      target: { value: "Synthetic reply" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send reply" }));
    await waitFor(() =>
      expect(call).toHaveBeenCalledWith("phone.notification", {
        id: "n",
        operation: "reply",
        text: "Synthetic reply",
        reply_key: "reply",
      }),
    );
    expect(screen.getByText("Synthetic message")).toBeVisible(); // Phone remains the authority; no optimistic deletion.
  });
  it("retains offline content while preventing remote actions", () => {
    render(
      <Phone
        state={state(false)}
        client={{ call: vi.fn(), subscribe: () => () => {} } as Client}
      />,
    );
    expect(screen.getByText("Offline")).toBeVisible();
    expect(screen.getByRole("button", { name: "Archive" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reply" })).toBeDisabled();
    expect(screen.getByText("Synthetic body")).toBeVisible();
  });
  it("distinguishes a disconnected feed from missing notification permission", () => {
    const fixture = state(false);
    fixture.phone!.notifications = [];
    fixture.phone!.devices[0].last_seen_at = "2026-10-12T10:00:00Z";
    const client = {
      call: vi.fn().mockResolvedValue({}),
      subscribe: () => () => {},
    } as Client;
    const view = render(<Phone state={fixture} client={client} />);
    expect(
      screen.getByRole("heading", { name: "Phone disconnected" }),
    ).toBeVisible();
    expect(screen.getByText(/Last seen/)).toBeVisible();
    expect(screen.queryByRole("heading", { name: "All clear" })).toBeNull();
    view.rerender(
      <Phone
        state={{
          ...fixture,
          phone: {
            ...fixture.phone!,
            devices: [
              {
                ...fixture.phone!.devices[0],
                online: true,
                capabilities: ["battery"],
              },
            ],
          },
        }}
        client={client}
      />,
    );
    expect(
      screen.getByRole("heading", { name: "Allow notifications" }),
    ).toBeVisible();
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
  // Pairing lives in the "Add a device" dialog; open it when it is not already open.
  function addDevice() {
    if (!screen.queryByRole("dialog")) fireEvent.click(screen.getByRole("button", { name: "Add a device" }));
  }
  function showQr() {
    addDevice();
    return screen.getByRole("button", { name: "Show pairing QR" });
  }

  it("offers pairing only on a paired computer and keeps the invitation file option", async () => {
    const call = vi.fn().mockResolvedValue({});
    const client = clientFor(call);
    const { rerender } = render(<Phone state={state()} client={client} />);
    expect(screen.queryByRole("group", { name: "Add a device" })).toBeNull();
    rerender(<Phone state={pairedState()} client={client} />);
    addDevice();
    fireEvent.click(screen.getByRole("button", { name: "Save invitation file" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("enrollment.export"));
    expect(screen.queryByRole("img", { name: "Pairing QR code" })).toBeNull();
  });

  it("shows a QR on request, prevents another while visible, and allows closing it", async () => {
    const call = vi.fn().mockResolvedValue(qr);
    render(<Phone state={pairedState()} client={clientFor(call)} />);
    fireEvent.click(showQr());
    expect(await screen.findByRole("img", { name: "Pairing QR code" })).toBeVisible();
    expect(call).toHaveBeenCalledExactlyOnceWith("enrollment.qr");
    expect(showQr()).toBeDisabled();
    expect(screen.getByRole("timer")).toHaveTextContent("Expires in 10:00");
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("img", { name: "Pairing QR code" })).toBeNull();
    expect(showQr()).toBeEnabled();
  });

  it("closes on admission of a new device without closing on ordinary status updates", async () => {
    const client = clientFor();
    const initial = pairedState();
    const { rerender } = render(<Phone state={initial} client={client} />);
    fireEvent.click(showQr());
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
    const client = clientFor(vi.fn().mockResolvedValue({ ...qr, expires_in: 1 }));
    render(<Phone state={pairedState()} client={client} />);
    addDevice(); // The dialog opens before the clock is faked; the QR's lifetime is what this checks.
    vi.useFakeTimers();
    try {
      await act(async () => { fireEvent.click(showQr()); });
      expect(screen.getByRole("img", { name: "Pairing QR code" })).toBeVisible();
      act(() => vi.advanceTimersByTime(1000));
      expect(screen.queryByRole("img", { name: "Pairing QR code" })).toBeNull();
    } finally { vi.useRealTimers(); }
    expect(screen.getByRole("status")).toHaveTextContent("pairing QR expired");
    expect(showQr()).toBeEnabled();
  });

  it("rejects a malformed response and leaves the file alternative available", async () => {
    render(<Phone state={pairedState()} client={clientFor(vi.fn().mockResolvedValue({ ...qr, modules: ["invalid"] }))} />);
    fireEvent.click(showQr());
    expect(await screen.findByRole("alert")).toHaveTextContent("Save an invitation file instead");
    expect(screen.queryByRole("img", { name: "Pairing QR code" })).toBeNull();
    expect(screen.getByRole("button", { name: "Save invitation file" })).toBeEnabled();
  });

  it("discards the QR when leaving the Phone page", async () => {
    const client = clientFor();
    const { unmount } = render(<Phone state={pairedState()} client={client} />);
    fireEvent.click(showQr());
    await screen.findByRole("img", { name: "Pairing QR code" });
    unmount();
    render(<Phone state={pairedState()} client={client} />);
    expect(screen.queryByRole("img", { name: "Pairing QR code" })).toBeNull();
    expect(showQr()).toBeEnabled();
  });
  it("clears the QR when initially unavailable device state arrives", async () => {
    const client = clientFor();
    const initial = { ...pairedState(), phone: undefined };
    const { rerender } = render(<Phone state={initial} client={client} />);
    fireEvent.click(showQr());
    await screen.findByRole("img", { name: "Pairing QR code" });
    rerender(<Phone state={pairedState()} client={client} />);
    expect(screen.queryByRole("img", { name: "Pairing QR code" })).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent("device list changed");
  });

  it.each(["unpair", "switch"])("clears the QR on a Hub %s", async (change) => {
    const client = clientFor();
    const initial = pairedState();
    const { rerender } = render(<Phone state={initial} client={client} />);
    fireEvent.click(showQr());
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
    fireEvent.click(showQr());
    expect(showQr()).toBeDisabled();
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
      fireEvent.click(showQr());
      vi.setSystemTime(new Date("2026-01-01T12:00:10Z"));
      await act(async () => { resolve(qr); });
      expect(screen.getByRole("timer")).toHaveTextContent("Expires in 9:50");
    } finally { vi.useRealTimers(); }
  });

});
