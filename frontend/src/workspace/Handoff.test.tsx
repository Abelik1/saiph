// SPDX-License-Identifier: AGPL-3.0-or-later
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Handoff } from "./Handoff";
import type { Client } from "./types";

describe("File Handoff", () => {
  it("opens a completed file only after a deliberate click with its local receipt id", async () => {
    const call = vi.fn().mockResolvedValue({});
    render(<Handoff items={[{ id: "receipt", kind: "file", file_id: "receipt", value: "Lecture.pdf", source: "phone", status: "ready" }]} devices={[]} client={{ call } as unknown as Client} />);
    expect(call).not.toHaveBeenCalled();
    expect(screen.getByText("Lecture.pdf")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Open" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("continuity.open", { id: "receipt" }));
  });

  it("uses the native picker for a file-capable computer without sending typed text or paths", async () => {
    const call = vi.fn().mockResolvedValue({});
    render(<Handoff items={[]} currentDeviceId="desktop" devices={[{ id: "desktop", name: "This computer", online: true, capabilities: ["files", "handoff"] }, { id: "laptop", name: "Laptop", online: true, capabilities: ["files"] }]} client={{ call } as unknown as Client} />);
    expect(screen.queryByRole("option", { name: "This computer" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Send a file" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("continuity.file.choose", { device_id: "laptop" }));
    expect(call).toHaveBeenCalledTimes(1);
  });
});
