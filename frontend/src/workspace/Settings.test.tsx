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
    expect(screen.getByText("This computer is paired with your Hub.")).toBeVisible();
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
    fireEvent.click(screen.getByRole("button", { name: "Save folder" }));
    expect(await screen.findByText("Cloud folder saved.")).toBeVisible();
    fireEvent.change(screen.getByLabelText("Cloud folder"), {
      target: { value: "/another/folder" },
    });
    expect(screen.queryByText("Cloud folder saved.")).toBeNull();
  });
  it("preserves unsaved connection and camera preferences across sections", async () => {
    const call = vi.fn().mockResolvedValue({});
    render(<Settings state={state} client={{ call } as unknown as Client} />);
    fireEvent.click(screen.getByRole("tab", { name: "Connections" }));
    fireEvent.change(screen.getByLabelText("Cloud folder"), {
      target: { value: "/unfinished/cloud" },
    });
    expect(screen.getByText(/Unsaved changes/)).toBeVisible();
    fireEvent.click(screen.getByRole("tab", { name: "Devices" }));
    fireEvent.click(screen.getByText("Legacy USB camera tools (advanced)", {selector:"summary span"}));
    await screen.findByText("Meeting-app configuration", {selector:"summary span"});
    fireEvent.click(screen.getByText("Meeting-app configuration", {selector:"summary span"}));
    fireEvent.change(screen.getByLabelText("Linux loopback device"), {
      target: { value: "/dev/video12" },
    });
    fireEvent.click(screen.getByRole("tab", { name: "Connections" }));
    expect(screen.getByLabelText("Cloud folder")).toHaveValue(
      "/unfinished/cloud",
    );
    expect(call).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Save folder" }));
    expect(await screen.findByText("Cloud folder saved.")).toBeVisible();
    expect(call).toHaveBeenCalledWith("settings.save", { cloud: { path: "/unfinished/cloud" } });
    expect(screen.getByText(/Unsaved changes/)).not.toBeVisible();
    fireEvent.click(screen.getByRole("tab", { name: "Devices" }));
    expect(screen.getByLabelText("Linux loopback device")).toHaveValue(
      "/dev/video12",
    );
  });
  it("lays out Connections like Settings → Phone: visible sections, switches that save on their own", async () => {
    const call = vi.fn().mockResolvedValue({});
    render(<Settings state={state} client={{ call } as unknown as Client} />);
    fireEvent.click(screen.getByRole("tab", { name: "Connections" }));
    for (const heading of ["Phone and this computer", "Quiet hours", "Cloud folders"]) {
      const section = screen.getByRole("heading", { name: heading });
      expect(section).toBeVisible();
      expect(section.closest("details")).toBeNull();
    }
    const clipboard = screen.getByRole("switch", { name: "Share clipboard" });
    expect(clipboard.closest("details")).toBeNull();
    expect(clipboard).toBeChecked();
    fireEvent.click(clipboard);
    await waitFor(() => expect(call).toHaveBeenCalledWith("settings.save", { link: { clipboard: false } }));
    // No native dropdowns or bare <details> remain on the page.
    expect(document.querySelector(".settings-content select:not([aria-hidden])")).toBeNull();
    expect(document.querySelectorAll(".settings-content details:not([data-slot=disclosure])")).toHaveLength(0);
  });
  it("keeps an unpaired self-hosted Hub folded away under its own disclosure", () => {
    const unpaired = { ...state, settings: { ...state.settings, hub: { paired: false } } } as unknown as State;
    render(<Settings state={unpaired} client={{ call: vi.fn() } as unknown as Client} />);
    fireEvent.click(screen.getByRole("tab", { name: "Connections" }));
    expect(screen.queryByRole("heading", { name: "Self-hosted Hub" })).toBeNull();
    const hub = screen.getByText("Self-hosted Hub", { selector: "summary span" }).closest("details")!;
    expect(hub).not.toHaveAttribute("open");
    expect(screen.getByLabelText("Saiph Hub address")).not.toBeVisible();
  });
});
