// SPDX-License-Identifier: AGPL-3.0-or-later
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { HotspotSettings } from "./HotspotSettings";
import type { Client } from "./types";

const status = { profiles: ["Home Wi-Fi", "Pixel Hotspot"], profile: "", auto: false, active: null, error: "", supported: true };

describe("Phone hotspot settings", () => {
  it("chooses a saved network and enables automatic reconnection", async () => {
    const call = vi.fn().mockResolvedValue({});
    render(<HotspotSettings hotspot={status} client={{ call } as unknown as Client} />);
    expect(screen.getByLabelText("Reconnect automatically when this computer has no network")).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Phone hotspot network"), { target: { value: "Pixel Hotspot" } });
    fireEvent.click(screen.getByLabelText("Reconnect automatically when this computer has no network"));
    fireEvent.click(screen.getByRole("button", { name: "Save hotspot" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("settings.save", { link: { hotspot: { profile: "Pixel Hotspot", auto: true } } }));
  });
  it("connects on request and reports the connection", async () => {
    const call = vi.fn().mockResolvedValue({});
    render(<HotspotSettings hotspot={{ ...status, profile: "Pixel Hotspot", active: "Pixel Hotspot" }} client={{ call } as unknown as Client} />);
    expect(screen.getByRole("status")).toHaveTextContent("Connected to your phone's hotspot.");
    fireEvent.click(screen.getByRole("button", { name: "Connect to Pixel Hotspot" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("hotspot.connect"));
  });
});
