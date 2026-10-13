// SPDX-License-Identifier: AGPL-3.0-or-later
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ContinuitySettings } from "./ContinuitySettings";
import type { Client } from "./types";

const settings = {
  cloud: {path:"C:/Cloud",enabled:true,recordings:true},
  link: {focus:true,dnd_sync:false,auto_copy_codes:false,battery_alerts:true,pause_media_on_calls:true,new_photo_notices:true,clipboard:false,timezone:"Europe/London",wake_hour:8,wake_minute:15,deskflow:{enabled:true},camera:{enabled:true}},
};

describe("continuity edition boundaries", () => {
  it("saves only core preferences and hides optional controls in Link", async () => {
    const call=vi.fn().mockResolvedValue({});
    render(<ContinuitySettings settings={settings} client={{call} as unknown as Client} workspace={false} backup={{configured:true,targets:{pi:{ok:true}}}} />);
    expect(screen.queryByText(/Transcribe|Encrypted backups|Windows Dynamic Lock settings|Pi backup/)).toBeNull();
    fireEvent.click(screen.getByRole("button",{name:"Save preferences"}));
    await waitFor(() => expect(call).toHaveBeenCalledWith("settings.save",{
      cloud:{path:"C:/Cloud",enabled:true},
      link:{focus:true,dnd_sync:false,auto_copy_codes:false,battery_alerts:true,pause_media_on_calls:true,new_photo_notices:true,clipboard:false,timezone:"Europe/London",wake_hour:8,wake_minute:15},
    }));
  });

  it("preserves optional preferences for the Workspace edition", async () => {
    const call=vi.fn().mockResolvedValue({});
    render(<ContinuitySettings settings={settings} client={{call} as unknown as Client} />);
    expect(screen.getByText("Transcribe finished Cloud recordings automatically")).toBeVisible();
    expect(screen.getByRole("button",{name:"Windows Dynamic Lock settings"})).toBeVisible();
    fireEvent.click(screen.getByRole("button",{name:"Save preferences"}));
    await waitFor(() => expect(call).toHaveBeenCalledWith("settings.save",settings));
  });
});
