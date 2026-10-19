// SPDX-License-Identifier: AGPL-3.0-or-later
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { PROGRESS_MS, UpdateButton } from "./UpdateButton";
import { Updates } from "./Updates";
import type { AppUpdate, AppUpdateState, Client, State } from "./types";

const release = {schema: 1, platform: "windows-x86_64", profile: "link", build: 12, version: "0.1.0-beta.12", sha256: "a".repeat(64), bytes: 58_000_000};

function update(state: AppUpdateState, changes: Partial<AppUpdate> = {}): AppUpdate {
  const offered = state !== "none";
  return {state, release: offered ? release : null, version: offered ? release.version : null, bytes: offered ? release.bytes : null,
    notes: offered ? "Faster photo sync." : "", source: "cloud", error: "", checked_at: 1_700_000_000, ...changes};
}

function client(answers: Record<string, unknown> = {}) {
  const call = vi.fn(async (method: string) => {
    if (!(method in answers)) throw new Error("unexpected " + method);
    const answer = answers[method];
    return typeof answer === "function" ? (answer as () => unknown)() : answer;
  });
  return {call, subscribe: () => () => {}} as unknown as Client & {call: typeof call};
}

afterEach(() => { vi.useRealTimers(); });

describe("footer Update button", () => {
  it("is absent when there is nothing to offer, and never asks the service itself", () => {
    const api = client();
    const { container, rerender } = render(<UpdateButton client={api} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<UpdateButton client={api} update={update("none")} />);
    expect(container).toBeEmptyDOMElement();
    expect(api.call).not.toHaveBeenCalled();
  });

  it("glows when an update is available and one click updates", async () => {
    let finish: (value: unknown) => void = () => {};
    const api = client({"app.update.now": () => new Promise(resolve => { finish = resolve; })});
    render(<UpdateButton client={api} update={update("available")} />);
    const button = screen.getByRole("button", {name: "Update Saiph to 0.1.0-beta.12"});
    expect(button).toHaveTextContent("Update to 0.1.0-beta.12");
    expect(button).toHaveClass("update-glow");
    expect(button).toHaveAttribute("title", expect.stringMatching(/download it, check it, install it and reopen/));
    fireEvent.click(button);
    expect(api.call).toHaveBeenCalledWith("app.update.now");
    expect(api.call.mock.calls[0]).toHaveLength(1);  // The page supplies no release, path or URL.
    expect(await screen.findByText("Checking…")).toBeVisible();
    expect(screen.getByRole("button", {name: /Update Saiph/})).toBeDisabled();
    await act(async () => finish({started: true, version: release.version}));
  });

  it("shows downloading with progress polled once a second, only while downloading", async () => {
    vi.useFakeTimers();
    const api = client({"app.update.progress": {state: "downloading", done: 29_000_000, total: 58_000_000}});
    const { rerender } = render(<UpdateButton client={api} update={update("downloading")} />);
    await act(async () => { await Promise.resolve(); });
    expect(screen.getByRole("status")).toHaveTextContent("Downloading… 50%");
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByRole("status")).not.toHaveClass("update-glow");
    await act(async () => { vi.advanceTimersByTime(PROGRESS_MS * 3); });
    expect(api.call).toHaveBeenCalledTimes(4);
    expect(PROGRESS_MS).toBeGreaterThanOrEqual(1000);
    rerender(<UpdateButton client={api} update={update("installing")} />);
    await act(async () => { vi.advanceTimersByTime(PROGRESS_MS * 10); });
    expect(api.call).toHaveBeenCalledTimes(4);
    expect(screen.getByRole("status")).toHaveTextContent("Installing… Saiph will reopen");
  });

  it("says when the download is being checked", async () => {
    const api = client({"app.update.progress": {state: "verifying", done: 58_000_000, total: 58_000_000}});
    render(<UpdateButton client={api} update={update("downloading")} />);
    expect(await screen.findByText("Checking the download…")).toBeVisible();
  });

  it("offers Restart to update once Settings downloaded the update", () => {
    const api = client({"app.update.now": {started: true}});
    render(<UpdateButton client={api} update={update("ready")} />);
    const button = screen.getByRole("button", {name: "Restart Saiph to finish updating to 0.1.0-beta.12"});
    expect(button).toHaveTextContent("Restart to update");
    expect(button).toHaveClass("update-glow");
    fireEvent.click(button);
    expect(api.call).toHaveBeenCalledWith("app.update.now");
  });

  it("shows a failure without a glow and retries on click", async () => {
    const api = client({"app.update.now": () => Promise.reject(new Error("Desktop update could not be verified."))});
    render(<UpdateButton client={api} update={update("failed", {error: "Desktop update could not be verified. Existing application and data were retained."})} />);
    const button = screen.getByRole("button", {name: "Update failed. Try again"});
    expect(button).not.toHaveClass("update-glow");
    expect(button).toHaveAttribute("title", "Desktop update could not be verified. Existing application and data were retained.");
    fireEvent.click(button);
    await waitFor(() => expect(api.call).toHaveBeenCalledWith("app.update.now"));
    // The failure stays shown through the shared state; no raw error is added.
    expect(await screen.findByRole("button", {name: "Update failed. Try again"})).toBeEnabled();
  });

  it("says Saiph is up to date when the check finds the update withdrawn", async () => {
    vi.useFakeTimers();
    const api = client({"app.update.now": {started: false, result: {available: false}}});
    const { rerender } = render(<UpdateButton client={api} update={update("available")} />);
    await act(async () => { fireEvent.click(screen.getByRole("button", {name: /Update Saiph/})); });
    rerender(<UpdateButton client={api} update={update("none")} />);
    expect(screen.getByRole("status")).toHaveTextContent("Saiph is up to date.");
    await act(async () => { vi.advanceTimersByTime(6000); });
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("uses no spinner or endless animation in any state", async () => {
    for (const state of ["available", "checking", "downloading", "ready", "installing", "failed"] as AppUpdateState[]) {
      const api = client({"app.update.progress": {state: "downloading", done: 0, total: 0}});
      const { container, unmount } = render(<UpdateButton client={api} update={update(state)} />);
      await act(async () => { await Promise.resolve(); });
      expect(container.querySelector(".animate-spin, [class*='animate-']")).toBeNull();
      unmount();
    }
  });

  it("glows with a finite animation that reduced motion turns off", () => {
    const motifs = readFileSync(resolve(process.cwd(), "src/design-system/motifs.css"), "utf8");
    const rule = /\.update-glow\s*\{([^}]*)\}/.exec(motifs)?.[1] || "";
    expect(rule).toMatch(/box-shadow:/);
    const animation = /animation:\s*([^;]+);/.exec(rule)?.[1] || "";
    expect(animation).toMatch(/saiph-update-breathe/);
    expect(animation).not.toMatch(/infinite/);
    expect(Number(/\s(\d+)$/.exec(animation.trim())?.[1])).toBeLessThanOrEqual(3);
    const reduced = motifs.slice(motifs.indexOf("@media (prefers-reduced-motion: reduce)"));
    expect(reduced).toMatch(/\.update-glow\s*\{\s*animation:\s*none;\s*\}/);
  });
});

describe("Settings → Updates follows the shared update", () => {
  it("offers the update found by the six-hourly check", async () => {
    let finish: (value: unknown) => void = () => {};
    const api = client({"app.update.download": () => new Promise(resolve => { finish = resolve; }),
      "app.update.progress": {state: "downloading", done: 0, total: 0}});
    render(<Updates client={api} cloud update={update("available")} />);
    expect(screen.getByText("Saiph 0.1.0-beta.12 is available.")).toBeVisible();
    expect(screen.getByText("Faster photo sync.")).toBeVisible();
    fireEvent.click(screen.getByRole("button", {name: "Download update (58 MB)"}));
    await waitFor(() => expect(api.call).toHaveBeenCalledWith("app.update.download", {release}));
    await act(async () => finish({staged: true, version: release.version}));
  });

  it("shows a footer download, install and failure", () => {
    const api = client({"app.update.progress": {state: "downloading", done: 0, total: 0}});
    const { rerender } = render(<Updates client={api} update={update("downloading")} />);
    expect(screen.getByRole("button", {name: "Check for updates"})).toBeDisabled();
    expect(screen.queryByRole("button", {name: /Download update/})).toBeNull();
    rerender(<Updates client={api} update={update("ready")} />);
    expect(screen.getByRole("button", {name: "Restart to update"})).toBeEnabled();
    rerender(<Updates client={api} update={update("installing")} />);
    expect(screen.getByText(/Saiph will close and reopen/)).toBeVisible();
    rerender(<Updates client={api} update={update("failed", {error: "Desktop download is incomplete or damaged"})} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Desktop download is incomplete or damaged");
  });
});

describe("footer in the window", () => {
  function state(app_update?: AppUpdate): State {
    return { app_version: "0.1.0-beta.11", app_update, hub_inbox: { items: [], synced_at: null, error: "" },
      setup: { completed: true, connected: true, show: false, mode: "hub", platform: "windows", tools: {}, linux: {} },
      settings: { hub: { paired: true, base_url: "", device_id: "desktop" }, machine: { name: "Desk", features: {} }, link: {} },
      hosted: { available: true, enabled: false, status: "off", identity: false, configured: true },
      phone: { status: "", error: "", notifications: [], devices: [] } } as unknown as State;
  }

  it("shows the glowing button beside the version only when an update is offered", async () => {
    for (const [value, shown] of [[undefined, false], [update("none"), false], [update("available"), true]] as const) {
      const call = vi.fn(async (method: string) => method === "state" ? state(value) : {});
      const { container, unmount } = render(<App providedClient={{ call, subscribe: () => () => undefined } as unknown as Client} />);
      const version = await screen.findByLabelText("Installed Saiph version");
      const footer = container.querySelector("footer.app-footer") as HTMLElement;
      expect(version).toHaveTextContent("Saiph 0.1.0-beta.11");
      expect(within(footer).queryByRole("button", {name: /Update Saiph/}) !== null).toBe(shown);
      expect(call).not.toHaveBeenCalledWith("app.update.now");
      expect(call).not.toHaveBeenCalledWith("app.update.check");
      unmount();
    }
  });
});
