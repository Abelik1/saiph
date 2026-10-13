// SPDX-License-Identifier: AGPL-3.0-or-later
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { BluetoothLockSettings } from "./BluetoothLockSettings";
import type { Client } from "./types";

const status = { supported: true, enabled: false, device: "", seconds: 30, error: "", windows: false,
  devices: [{ address: "AA:BB:CC:DD:EE:FF", name: "Galaxy A55" }] };

describe("Lock when my phone leaves", () => {
  it("saves the chosen Bluetooth phone on Linux", async () => {
    const call = vi.fn().mockResolvedValue({});
    render(<BluetoothLockSettings status={status} client={{ call } as unknown as Client} />);
    fireEvent.click(screen.getByLabelText("Lock this computer when my phone leaves"));
    expect(screen.getByRole("button", { name: "Save automatic lock" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Phone"), { target: { value: "AA:BB:CC:DD:EE:FF" } });
    fireEvent.click(screen.getByRole("button", { name: "Save automatic lock" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("settings.save", { link: { bt_lock: { enabled: true, device: "AA:BB:CC:DD:EE:FF", seconds: 30 } } }));
  });
  it("points Windows to Dynamic Lock", () => {
    render(<BluetoothLockSettings status={{ ...status, supported: false, windows: true }} client={{ call: vi.fn() } as unknown as Client} />);
    expect(screen.getByRole("button", { name: "Open sign-in options" })).toBeVisible();
  });
});
