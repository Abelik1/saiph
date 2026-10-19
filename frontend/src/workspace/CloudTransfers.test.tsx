// SPDX-License-Identifier: AGPL-3.0-or-later
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { CloudTransfers, fileSize, offerExpiry, transferStatus } from "./CloudTransfers";
import { PhoneTabs, type PhoneFeatureState } from "./PhoneTabs";
import type { Client, HostedTransfer } from "./types";
import { openTab } from "../test-helpers";

const client = (call = vi.fn().mockResolvedValue({ queued: true })) => ({ call, subscribe: () => () => {} }) as unknown as Client;
const base: HostedTransfer = { id: "t1", name: "Synthetic holiday.jpg", size: 3 * 1048576, target: "dev_phone", target_name: "Synthetic phone",
  state: "queued", error: "", progress: 0, attempts: 0 };
const features: PhoneFeatureState = { threads: [], messages: [], calls: [], photos: [], files: [] };
const phone = { id: "dev_phone", name: "Synthetic phone", online: true, hosted: true, capabilities: ["files"] };

describe("Saiph Cloud file transfers", () => {
  it("names each state in plain words", () => {
    expect(transferStatus(base)).toBe("Waiting to send to Synthetic phone");
    expect(transferStatus({ ...base, state: "sending", progress: 0.42 })).toBe("Sending to Synthetic phone · 42%");
    expect(transferStatus({ ...base, state: "retrying", retry_in: 8 })).toBe("Connection lost · retrying in 8 s");
    expect(transferStatus({ ...base, state: "sent", progress: 1 })).toBe("Sent to Synthetic phone");
    expect(transferStatus({ ...base, state: "failed", error: "Saiph Cloud stayed unreachable for 10 minutes. Nothing was sent." }))
      .toBe("Saiph Cloud stayed unreachable for 10 minutes. Nothing was sent.");
    expect(fileSize(3 * 1048576)).toBe("3.0 MB");
    expect(fileSize(42)).toBe("0.1 KB");
  });

  it("shows progress while sending and retrying, and no buttons until it fails", () => {
    const { rerender } = render(<CloudTransfers transfers={[{ ...base, state: "sending", progress: 0.5 }]} client={client()} />);
    expect(screen.getByRole("progressbar", { name: "Sending Synthetic holiday.jpg" })).toHaveAttribute("aria-valuenow", "50");
    expect(screen.queryByRole("button")).toBeNull();
    rerender(<CloudTransfers transfers={[{ ...base, state: "retrying", progress: 0.5, retry_in: 4 }]} client={client()} />);
    expect(screen.getByRole("status")).toHaveTextContent("Connection lost · retrying in 4 s");
    expect(screen.getByRole("progressbar")).toBeVisible();
  });

  it("offers Retry and Dismiss after a final failure", async () => {
    const call = vi.fn().mockResolvedValue({ queued: true });
    render(<CloudTransfers transfers={[{ ...base, state: "failed", error: "Nothing was sent." }]} client={client(call)} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Nothing was sent.");
    fireEvent.click(screen.getByRole("button", { name: "Retry Synthetic holiday.jpg" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("hosted.file.retry", { id: "t1" }));
    fireEvent.click(screen.getByRole("button", { name: "Dismiss Synthetic holiday.jpg" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("hosted.file.dismiss", { id: "t1" }));
  });

  it("says when an offer expires", () => {
    expect(offerExpiry(1000 + 250, 1000)).toBe("Save within 5 min");
    expect(offerExpiry(1000 + 40, 1000)).toBe("Save within 40 s");
    expect(offerExpiry(999, 1000)).toBe("Expired · ask the sender to share it again");
    expect(offerExpiry(undefined)).toBe("Ready to save");
  });

  it("shows only this phone's sends and a brief Sent state in the Share tab", () => {
    render(<PhoneTabs features={features} phone={phone} client={client()}
      cloudTransfers={[{ ...base, state: "sent", progress: 1 }, { ...base, id: "t2", name: "Other.txt", target: "dev_laptop", target_name: "Laptop" }]}
      cloudOffers={[{ id: "o1", source: "dev_phone", name: "Synthetic scan.pdf", size: 2048, expires_at: Date.now() / 1000 + 120 }]} />);
    openTab("Share");
    expect(screen.getByText(/Sent to Synthetic phone/)).toBeVisible();
    expect(screen.queryByText("Other.txt")).toBeNull();
    expect(screen.getByText(/2\.0 KB · Save within 2 min/)).toBeVisible();
  });
});

describe("Files over the local network", () => {
  it("says it is connecting, then sending directly", () => {
    expect(transferStatus({ ...base, state: "connecting", route: "lan" })).toBe("Connecting to Synthetic phone on your network…");
    expect(transferStatus({ ...base, state: "sending", route: "lan", progress: 0.3 })).toBe("Sending to Synthetic phone directly · 30%");
    render(<CloudTransfers transfers={[{ ...base, state: "connecting", route: "lan" }]} client={client()} />);
    expect(screen.queryByRole("progressbar")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("shows a received file's progress, then Save even while the phone is offline", async () => {
    const call = vi.fn().mockResolvedValue({ path: "C:/Synthetic/Downloads/Saiph/Synthetic video.mp4" });
    const receiving = { id: "o2", source: "dev_phone", route: "lan" as const, name: "Synthetic video.mp4", size: 500 * 1048576, state: "receiving" as const, progress: 0.25 };
    const offline = { ...phone, online: false };
    const { rerender } = render(<PhoneTabs features={features} phone={offline} client={client(call)} cloudOffers={[receiving]} />);
    openTab("Share");
    expect(screen.getByRole("progressbar", { name: "Receiving Synthetic video.mp4" })).toHaveAttribute("aria-valuenow", "25");
    expect(screen.getByText("500.0 MB · Receiving over your network · 25%")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Save Synthetic video.mp4" })).toBeNull();
    rerender(<PhoneTabs features={features} phone={offline} client={client(call)}
      cloudOffers={[{ ...receiving, state: "ready", progress: 1, expires_at: Date.now() / 1000 + 1700 }]} />);
    expect(screen.getByText("500.0 MB · Received over your network · Save within 29 min")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Save Synthetic video.mp4" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("hosted.file.save", { id: "o2" }));
  });

  it("shows why a file was not received, with Dismiss", async () => {
    const call = vi.fn().mockResolvedValue({ ok: true });
    render(<PhoneTabs features={features} phone={phone} client={client(call)} cloudOffers={[{ id: "o3", source: "dev_phone", route: "lan",
      name: "Synthetic.bin", size: 2048, state: "failed", error: "Not enough free space for Synthetic.bin (0.1 MB). Free some space and ask to send it again." }]} />);
    openTab("Share");
    expect(screen.getByRole("alert")).toHaveTextContent("Not enough free space for Synthetic.bin");
    fireEvent.click(screen.getByRole("button", { name: "Dismiss Synthetic.bin" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("hosted.file.dismiss", { id: "o3" }));
  });
});
