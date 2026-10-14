// SPDX-License-Identifier: AGPL-3.0-or-later
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import App from "../App";
import { SetupWizard } from "./SetupWizard";
import { UsageSettings } from "./UsageSharing";
import type { Client, State, UsageBatch, UsageState } from "./types";

const batch: UsageBatch = { schema: 1, day: "2026-10-14", app: "desktop", platform: "windows", version: "0.1.0-beta.5",
  mode: "hosted", install_age: "7-29", stage: "phone_added", features: { clipboard_sent: "6-20" } };
const ask: UsageState = { available: true, consent: null, pending: [], last_sent: null };

function state(usage: UsageState | undefined, show = false): State {
  return { usage, hub_inbox: { items: [], synced_at: null, error: "" }, setup: { completed: !show, connected: true, show, mode: "hub", platform: "windows", tools: {}, linux: {} },
    settings: { hub: { paired: true, base_url: "", device_id: "desktop" }, machine: { name: "Desk", features: {} }, link: {} },
    hosted: { available: true, enabled: false, status: "off", identity: false, configured: true },
    phone: { status: "", error: "", notifications: [], devices: [] } } as unknown as State;
}

describe("Anonymous usage agreement", () => {
  it("is asked once for existing users with two equal choices and nothing pre-selected", async () => {
    const call = vi.fn(async (method: string) => method === "state" ? state(ask) : {});
    render(<App providedClient={{ call, subscribe: () => () => undefined } as unknown as Client} />);
    expect(await screen.findByRole("dialog", { name: "Help improve Saiph?" })).toBeVisible();
    expect(screen.getByText(/No account or device ID is attached/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Don't share" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("usage.consent", { granted: false }));
    expect(call).not.toHaveBeenCalledWith("usage.screen", expect.anything());
  });

  it("is not asked in builds that cannot send, nor after a choice", async () => {
    for (const usage of [{ ...ask, available: false }, { ...ask, consent: "declined" as const }, undefined]) {
      const call = vi.fn(async (method: string) => method === "state" ? state(usage) : {});
      const { unmount } = render(<App providedClient={{ call, subscribe: () => () => undefined } as unknown as Client} />);
      await screen.findByRole("navigation", { name: "Main navigation" });
      expect(screen.queryByRole("dialog", { name: "Help improve Saiph?" })).toBeNull();
      unmount();
    }
  });

  it("counts screens only after the owner agreed", async () => {
    const call = vi.fn(async (method: string) => method === "state" ? state({ ...ask, consent: "granted" }) : {});
    render(<App providedClient={{ call, subscribe: () => () => undefined } as unknown as Client} />);
    await waitFor(() => expect(call).toHaveBeenCalledWith("usage.screen", { screen: "phone" }));
  });

  it("is a setup step that records the choice and moves on", async () => {
    const call = vi.fn().mockResolvedValue({});
    render(<SetupWizard state={state(ask, true)} client={{ call } as unknown as Client} close={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /self-host my own Hub/ }));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByRole("list", { name: "Setup steps" })).toHaveTextContent("Usage statistics");
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Skip for now" }));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByText(/Only needed for some features/);
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(await screen.findByRole("button", { name: "Share anonymous usage" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("usage.consent", { granted: true }));
    expect(await screen.findByText("Saiph is ready")).toBeVisible();
  });

  it("skips the setup step in builds that cannot send", async () => {
    render(<SetupWizard state={state({ ...ask, available: false }, true)} client={{ call: vi.fn().mockResolvedValue({}) } as unknown as Client} close={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /self-host my own Hub/ }));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByRole("list", { name: "Setup steps" })).not.toHaveTextContent("Usage statistics");
  });

  it("shows exactly what will be and was sent, and turning it off deletes counts", async () => {
    const call = vi.fn().mockResolvedValue({});
    render(<UsageSettings usage={{ available: true, consent: "granted", pending: [batch], last_sent: { ...batch, day: "2026-10-13" } }} client={{ call } as unknown as Client} />);
    fireEvent.click(screen.getByText("See what Saiph sends"));
    expect(screen.getByLabelText("Usage batch for 2026-10-14")).toHaveTextContent('"clipboard_sent": "6-20"');
    expect(screen.getByLabelText("Usage batch for 2026-10-13")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Stop sharing and delete local counts" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("usage.consent", { granted: false }));
  });
});
