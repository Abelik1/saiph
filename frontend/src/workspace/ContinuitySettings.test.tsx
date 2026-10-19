// SPDX-License-Identifier: AGPL-3.0-or-later
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ContinuitySettings } from "./ContinuitySettings";
import type { Client } from "./types";

const settings = {
  cloud: {path:"C:/Cloud",enabled:true,recordings:true},
  link: {focus:true,dnd_sync:false,auto_copy_codes:false,battery_alerts:true,pause_media_on_calls:true,new_photo_notices:true,ring_computer:true,clipboard:false,timezone:"Europe/London",wake_hour:8,wake_minute:15,deskflow:{enabled:true},camera:{enabled:true}},
};

describe("Connections preferences", () => {
  it("shows every preference as a visible switch in its section, with no dropdown to open", () => {
    render(<ContinuitySettings settings={settings} client={{call: vi.fn()} as unknown as Client} workspace={false} />);
    const expected: [string, boolean][] = [
      ["Share clipboard", false], ["Copy verification codes", false], ["New photos and screenshots", true], ["Low battery alerts", true],
      ["Pause media during calls", true], ["Find this computer", true], ["Sync Do Not Disturb", false], ["Follow the shared sleep plan", true], ["Use Cloud folders", true],
    ];
    for (const [name, checked] of expected) {
      const control = screen.getByRole("switch", { name });
      expect(control).toBeVisible();
      expect(control.closest("details")).toBeNull();
      expect(control).toHaveAttribute("aria-checked", String(checked));
    }
    expect(document.querySelector("details")).toBeNull();
    for (const heading of ["Phone and this computer", "Quiet hours", "Cloud folders"]) expect(screen.getByRole("heading", { name: heading })).toBeVisible();
  });

  it("uses the same defaults as the desktop when nothing is saved yet", () => {
    render(<ContinuitySettings settings={{}} client={{call: vi.fn()} as unknown as Client} workspace={false} />);
    expect(screen.getByRole("switch", { name: "Share clipboard" })).toBeChecked();
    expect(screen.getByRole("switch", { name: "Copy verification codes" })).not.toBeChecked();
    expect(screen.getByRole("switch", { name: "Sync Do Not Disturb" })).toBeChecked();
    expect(screen.getByLabelText("Quiet hours end")).toHaveValue("07:00");
    expect(screen.getByLabelText("Focus timezone")).toHaveValue("Europe/London");
  });

  it("saves each switch on its own and only the core preference it changes in Link", async () => {
    const call=vi.fn().mockResolvedValue({});
    render(<ContinuitySettings settings={settings} client={{call} as unknown as Client} workspace={false} backup={{configured:true,targets:{pi:{ok:true}}}} />);
    expect(screen.queryByText(/Transcribe|Encrypted backups|Windows Dynamic Lock settings|Pi backup/)).toBeNull();
    fireEvent.click(screen.getByRole("switch", { name: "Copy verification codes" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("settings.save", { link: { auto_copy_codes: true } }));
    fireEvent.click(screen.getByRole("switch", { name: "Sync Do Not Disturb" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("settings.save", { link: { dnd_sync: true } }));
    fireEvent.click(screen.getByRole("switch", { name: "Use Cloud folders" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("settings.save", { cloud: { enabled: false } }));
    expect(call).toHaveBeenCalledTimes(3);
  });

  it("explains a switch that could not be saved next to it", async () => {
    const call = vi.fn().mockRejectedValue(new Error("Continuity preferences are on or off."));
    render(<ContinuitySettings settings={settings} client={{call} as unknown as Client} workspace={false} />);
    fireEvent.click(screen.getByRole("switch", { name: "Low battery alerts" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Continuity preferences are on or off.");
    expect(screen.getByRole("switch", { name: "Low battery alerts" })).toBeEnabled();
  });

  it("sends Workspace the whole preference set, so other device preferences are kept", async () => {
    const call = vi.fn().mockResolvedValue({});
    render(<ContinuitySettings settings={settings} client={{ call } as unknown as Client} />);
    expect(screen.getByRole("switch", { name: "Transcribe recordings" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Windows Dynamic Lock settings" })).toBeVisible();
    fireEvent.click(screen.getByRole("switch", { name: "Share clipboard" }));
    // Workspace keeps device preferences such as Deskflow and camera.
    await waitFor(() => expect(call).toHaveBeenCalledWith("settings.save", { link: { ...settings.link, clipboard: true } }));
    fireEvent.click(screen.getByRole("switch", { name: "Transcribe recordings" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("settings.save", { cloud: { ...settings.cloud, recordings: false } }));
  });

  it("browses without saving, saves the folder and saves a timezone plus hour and minute", async () => {
    const call = vi.fn().mockResolvedValueOnce({ path: "" }).mockResolvedValueOnce({ path: "/chosen/cloud" }).mockResolvedValue({});
    render(<ContinuitySettings settings={settings} client={{ call } as unknown as Client} platform="linux" workspace={false} />);
    fireEvent.click(screen.getByRole("button", { name: "Browse Cloud folder" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Browse Cloud folder" })).toBeEnabled());
    expect(screen.getByLabelText("Cloud folder")).toHaveValue("C:/Cloud");
    fireEvent.click(screen.getByRole("button", { name: "Browse Cloud folder" }));
    await waitFor(() => expect(screen.getByLabelText("Cloud folder")).toHaveValue("/chosen/cloud"));
    expect(screen.getByText(/Unsaved changes/)).toBeVisible();
    expect(call).not.toHaveBeenCalledWith("settings.save", expect.anything());
    fireEvent.click(screen.getByRole("button", { name: "Save folder" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("settings.save", { cloud: { path: "/chosen/cloud" } }));
    const timezone = screen.getByLabelText("Focus timezone");
    expect(timezone).toHaveAttribute("list");
    fireEvent.change(timezone, { target: { value: "Europe/Dublin" } });
    fireEvent.change(screen.getByLabelText("Quiet hours end"), { target: { value: "09:45" } });
    fireEvent.click(screen.getByRole("button", { name: "Save quiet hours" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("settings.save", { link: { timezone: "Europe/Dublin", wake_hour: 9, wake_minute: 45 } }));
    expect(await screen.findByText("Quiet hours saved.")).toBeVisible();
    expect(screen.getByText(/GNOME Do Not Disturb/)).toBeVisible();
  });

  it("explains invalid timezones without sending invalid settings", async () => {
    const call = vi.fn();
    render(<ContinuitySettings settings={settings} client={{ call } as unknown as Client} />);
    fireEvent.change(screen.getByLabelText("Focus timezone"), { target: { value: "Invalid/City" } });
    fireEvent.click(screen.getByRole("button", { name: "Save quiet hours" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Choose a valid timezone");
    expect(call).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Windows Dynamic Lock settings" })).toBeVisible();
  });

  it("disables quiet-hours times while the shared sleep plan is off", () => {
    render(<ContinuitySettings settings={{ link: { ...settings.link, focus: false } }} client={{ call: vi.fn() } as unknown as Client} platform="linux" />);
    expect(screen.getByLabelText("Focus timezone")).toBeDisabled();
    expect(screen.getByLabelText("Quiet hours end")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Save quiet hours" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Windows Dynamic Lock settings" })).toBeNull();
  });
});
