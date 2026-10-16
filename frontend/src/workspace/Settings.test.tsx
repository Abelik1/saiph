// SPDX-License-Identifier: AGPL-3.0-or-later
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Settings } from "./Settings";
import type { Client, State } from "./types";
const state = {
  modules: { workspace: { installed: false, enabled: false } },
  settings: {
    machine: { name: "Studio", features: {} },
    hub: { paired: true },
    cloud: { enabled: true },
    link: {},
    start_with_windows: false,
    close_to_tray: true,
  },
} as unknown as State;
describe("Settings navigation and feedback", () => {
  it("supports keyboard section navigation and preserves the computer-name draft", () => {
    render(
      <Settings
        state={state}
        client={{ call: vi.fn().mockResolvedValue({}) } as unknown as Client}
      />,
    );
    fireEvent.change(screen.getByLabelText("Computer name"), {
      target: { value: "My studio" },
    });
    const general = screen.getByRole("tab", { name: "General" });
    general.focus();
    fireEvent.keyDown(general, { key: "ArrowDown" });
    expect(screen.getByRole("tab", { name: "Connections" })).toHaveFocus();
    expect(screen.getByText("This computer is paired.")).toBeVisible();
    fireEvent.click(screen.getByRole("tab", { name: "General" }));
    expect(screen.getByLabelText("Computer name")).toHaveValue("My studio");
  });
  it("uses accessible startup switches and confirms successful preference saves", async () => {
    const call = vi.fn().mockResolvedValue({});
    render(<Settings state={state} client={{ call } as unknown as Client} />);
    const startup = screen.getByRole("switch", {
      name: "Start when I sign in",
    });
    expect(startup).toHaveAttribute("aria-checked", "false");
    fireEvent.click(startup);
    await waitFor(() =>
      expect(call).toHaveBeenCalledWith("settings.save", {
        start_with_windows: true,
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Save this computer" }));
    expect(
      await screen.findByText("Computer preferences saved."),
    ).toBeVisible();
    fireEvent.click(screen.getByRole("tab", { name: "Connections" }));
    expect(screen.getByText("Computer preferences saved.")).not.toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Save preferences" }));
    expect(await screen.findByText("Preferences saved.")).toBeVisible();
    fireEvent.change(screen.getByLabelText("Cloud folder"), {
      target: { value: "/another/folder" },
    });
    expect(screen.queryByText("Preferences saved.")).toBeNull();
  });
  it("preserves unsaved connection and camera preferences across sections", async () => {
    const call = vi.fn().mockResolvedValue({});
    render(<Settings state={state} client={{ call } as unknown as Client} />);
    fireEvent.click(screen.getByRole("tab", { name: "Connections" }));
    fireEvent.change(screen.getByLabelText("Cloud folder"), {
      target: { value: "/unfinished/cloud" },
    });
    fireEvent.click(screen.getByLabelText("Use Cloud folders"));
    expect(screen.getByText(/Unsaved changes/)).toBeVisible();
    fireEvent.click(screen.getByRole("tab", { name: "Devices" }));
    fireEvent.click(screen.getByText("Meeting-app configuration", {selector:"summary span"}));
    fireEvent.change(screen.getByLabelText("Linux loopback device"), {
      target: { value: "/dev/video12" },
    });
    fireEvent.click(screen.getByRole("tab", { name: "Connections" }));
    expect(screen.getByLabelText("Cloud folder")).toHaveValue(
      "/unfinished/cloud",
    );
    expect(screen.getByLabelText("Use Cloud folders")).not.toBeChecked();
    expect(call).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Save preferences" }));
    expect(await screen.findByText("Preferences saved.")).toBeVisible();
    expect(screen.getByText(/Unsaved changes/)).not.toBeVisible();
    fireEvent.click(screen.getByRole("tab", { name: "Devices" }));
    expect(screen.getByLabelText("Linux loopback device")).toHaveValue(
      "/dev/video12",
    );
  });
});
