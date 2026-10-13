// SPDX-License-Identifier: AGPL-3.0-or-later
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ContinuitySettings } from "./ContinuitySettings";
import type { Client } from "./types";

const settings = {
  cloud: {path:"C:/Cloud",enabled:true,recordings:true},
  link: {focus:true,dnd_sync:false,auto_copy_codes:false,battery_alerts:true,pause_media_on_calls:true,new_photo_notices:true,ring_computer:true,clipboard:false,timezone:"Europe/London",wake_hour:8,wake_minute:15,deskflow:{enabled:true},camera:{enabled:true}},
};

describe("continuity edition boundaries", () => {
  it("saves only core preferences and hides optional controls in Link", async () => {
    const call=vi.fn().mockResolvedValue({});
    render(<ContinuitySettings settings={settings} client={{call} as unknown as Client} workspace={false} backup={{configured:true,targets:{pi:{ok:true}}}} />);
    expect(screen.queryByText(/Transcribe|Encrypted backups|Windows Dynamic Lock settings|Pi backup/)).toBeNull();
    fireEvent.click(screen.getByRole("button",{name:"Save preferences"}));
    await waitFor(() => expect(call).toHaveBeenCalledWith("settings.save",{
      cloud:{path:"C:/Cloud",enabled:true},
      link:{focus:true,dnd_sync:false,auto_copy_codes:false,battery_alerts:true,pause_media_on_calls:true,new_photo_notices:true,ring_computer:true,clipboard:false,timezone:"Europe/London",wake_hour:8,wake_minute:15},
    }));
  });

  it("saves Workspace continuity without overwriting other device preferences", async () => {
    const call = vi.fn().mockResolvedValue({});
    render(
      <ContinuitySettings
        settings={settings}
        client={{ call } as unknown as Client}
      />,
    );
    expect(
      screen.getByText("Transcribe finished Cloud recordings automatically"),
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Windows Dynamic Lock settings" }),
    ).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Save preferences" }));
    await waitFor(() =>
      expect(call).toHaveBeenCalledWith("settings.save", {
        cloud: settings.cloud,
        // Workspace keeps device preferences such as Deskflow and camera.
        link: settings.link,
      }),
    );
  });
  it("browses without saving and saves a timezone plus hour and minute", async () => {
    const call = vi
      .fn()
      .mockResolvedValueOnce({ path: "" })
      .mockResolvedValueOnce({ path: "/chosen/cloud" })
      .mockResolvedValue({});
    render(
      <ContinuitySettings
        settings={settings}
        client={{ call } as unknown as Client}
        platform="linux"
      />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Browse Cloud folder" }),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Browse Cloud folder" }),
      ).toBeEnabled(),
    );
    expect(screen.getByLabelText("Cloud folder")).toHaveValue("C:/Cloud");
    fireEvent.click(
      screen.getByRole("button", { name: "Browse Cloud folder" }),
    );
    await waitFor(() =>
      expect(screen.getByLabelText("Cloud folder")).toHaveValue(
        "/chosen/cloud",
      ),
    );
    expect(screen.getByText(/Unsaved changes/)).toBeVisible();
    expect(call).not.toHaveBeenCalledWith("settings.save", expect.anything());
    const timezone = screen.getByLabelText("Focus timezone");
    expect(timezone).toHaveAttribute("list");
    fireEvent.change(timezone, { target: { value: "Europe/Dublin" } });
    fireEvent.change(screen.getByLabelText("Quiet hours end"), {
      target: { value: "09:45" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save preferences" }));
    await waitFor(() =>
      expect(call).toHaveBeenCalledWith(
        "settings.save",
        expect.objectContaining({
          link: expect.objectContaining({
            focus: true,
            dnd_sync: false,
            clipboard: false,
            timezone: "Europe/Dublin",
            wake_hour: 9,
            wake_minute: 45,
          }),
        }),
      ),
    );
    expect(
      screen.queryByRole("button", { name: "Windows Dynamic Lock settings" }),
    ).toBeNull();
  });
  it("explains invalid timezones without sending invalid settings", async () => {
    const call = vi.fn();
    render(
      <ContinuitySettings
        settings={settings}
        client={{ call } as unknown as Client}
      />,
    );
    fireEvent.change(screen.getByLabelText("Focus timezone"), {
      target: { value: "Invalid/City" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save preferences" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Choose a valid timezone",
    );
    expect(call).not.toHaveBeenCalled();
  });
});
