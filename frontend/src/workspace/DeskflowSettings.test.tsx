// SPDX-License-Identifier: AGPL-3.0-or-later
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DeskflowSettings } from "./DeskflowSettings";
import { chooseOption } from "../test-helpers";
import { Settings as SettingsPage } from "./Settings";
import type { Client, Settings, State } from "./types";

describe("Deskflow Advanced settings", () => {
  it("defaults to enabled without claiming connection or starting a tool", () => {
    const call = vi.fn();
    render(<DeskflowSettings settings={{} as Settings} client={{ call } as unknown as Client} />);
    expect(screen.getByLabelText("Share keyboard and mouse")).toBeChecked();
    expect(screen.getByRole("status")).toHaveTextContent("Connection has not been verified here");
    expect(call).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /connect|refresh|sync/i })).not.toBeInTheDocument();
  });

  it("preserves retained options while saving only Deskflow preferences", async () => {
    const call = vi.fn().mockResolvedValue({});
    const retained = { enabled: true, role: "laptop" as const, desktop: "100.64.0.2", local: "100.64.0.7", certificate: "/private/deskflow.pem", executable: "/usr/bin/deskflow-core" };
    render(<DeskflowSettings settings={{ link: { deskflow: retained, camera: { enabled: true }, clipboard: true } } as Settings} error="Complete Deskflow's one-time certificate trust setup on both computers." client={{ call } as unknown as Client} />);
    expect(screen.getByRole("status")).toHaveTextContent("one-time certificate trust setup");
    chooseOption("This computer's role", "Desktop · keyboard and mouse host");
    fireEvent.change(screen.getByLabelText("This computer's mesh address"), { target: { value: "100.64.0.2" } });
    fireEvent.click(screen.getByRole("button", { name: "Save sharing preferences" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("settings.save", { link: { deskflow: { ...retained, role: "desktop", local: "100.64.0.2" } } }));
    expect(call).toHaveBeenCalledTimes(1);
  });

  it("can disable sharing without submitting empty optional addresses or tool paths", async () => {
    const call = vi.fn().mockResolvedValue({});
    render(<DeskflowSettings settings={{ link: { deskflow: { role: "laptop", desktop: "100.64.0.2", local: "", executable: "" } } } as Settings} client={{ call } as unknown as Client} />);
    fireEvent.click(screen.getByLabelText("Share keyboard and mouse"));
    fireEvent.click(screen.getByRole("button", { name: "Save sharing preferences" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("settings.save", { link: { deskflow: { enabled: false, role: "laptop", desktop: "100.64.0.2" } } }));
    expect(screen.getByText("Sharing is switched off in these preferences.")).toBeVisible();
    expect(await screen.findByText("Sharing preferences saved.")).toBeVisible();
  });

  it("keeps mesh and certificate controls inside the Advanced tab", () => {
    const call = vi.fn().mockResolvedValue({});
    const state = { settings: { ai: {}, default_attention: "normal", machine: { name: "desktop", features: {} }, selected_project: "", hub: {}, link: { deskflow: { enabled: true } } }, deskflow: { error: "Deskflow is not installed on this computer." }, api: { running: false }, skills: [] } as unknown as State;
    render(<SettingsPage state={state} client={{ call } as unknown as Client} />);
    expect(screen.queryByLabelText("Desktop mesh address")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Advanced" }));
    expect(screen.getByLabelText("Desktop mesh address")).toBeVisible();
    expect(screen.getByLabelText("Existing Deskflow certificate path")).toBeVisible();
    expect(screen.getByText("Deskflow is not installed on this computer.")).toBeVisible();
    expect(call).not.toHaveBeenCalled();
  });
  it("shows setup checks, fills detected values and restarts on request", async () => {
    const call = vi.fn().mockResolvedValue({});
    const status = { error: "", running: false, setup: { executable: "C:/Program Files/Deskflow/deskflow-core.exe", certificates: ["C:/ProgramData/Deskflow/tls/deskflow.pem"],
      trust_file: "C:/ProgramData/Deskflow/tls/trusted-clients", trusted: false, mesh_addresses: ["100.70.1.2"] } };
    render(<DeskflowSettings settings={{ link: { deskflow: { enabled: true, role: "desktop", desktop: "100.70.1.2" } } } as Settings} status={status} client={{ call } as unknown as Client} />);
    const checks = screen.getByRole("list", { name: "Deskflow setup checks" });
    expect(checks).toHaveTextContent("✓ Deskflow installed");
    expect(checks).toHaveTextContent("○ Peer fingerprint approved");
    fireEvent.click(screen.getByRole("button", { name: "Use detected settings" }));
    expect(screen.getByLabelText("Existing Deskflow certificate path")).toHaveValue("C:/ProgramData/Deskflow/tls/deskflow.pem");
    expect(screen.getByLabelText("This computer's mesh address")).toHaveValue("100.70.1.2");
    fireEvent.click(screen.getByRole("button", { name: "Restart sharing" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("deskflow.restart"));
  });
});
