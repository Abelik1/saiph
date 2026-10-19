// SPDX-License-Identifier: AGPL-3.0-or-later
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AppGrid, arrangeApps, monogramHue, type PhoneApp } from "./PhoneAppGrid";
import { LiveBadge, liveLabel, liveSources } from "./LiveIndicator";
import type { Client } from "./types";

const app = (name: string, pkg = `com.example.${name.toLowerCase()}`): PhoneApp => ({ package: pkg, name, system: false });
const apps = [app("Calendar"), app("Chat"), app("Maps"), app("Music"), app("Notes")];
const PNG = "data:image/png;base64,iVBORw0KGgo=";
const noop = () => undefined;

describe("arrangeApps", () => {
  it("puts pinned apps first in pin order, then the most opened, without repeats", () => {
    const groups = arrangeApps(apps, ["com.example.notes", "com.example.gone", "com.example.chat"],
      { "com.example.maps": 5, "com.example.chat": 9, "com.example.music": 2, "com.example.calendar": 0 }, "");
    expect(groups.pinned.map((row) => row.name)).toEqual(["Notes", "Chat"]);
    expect(groups.mostUsed.map((row) => row.name)).toEqual(["Maps", "Music"]); // Chat is already pinned; never-opened apps are left out.
    expect(groups.all).toHaveLength(5);
  });
  it("keeps at most eight most used apps, most opened first", () => {
    const many = Array.from({ length: 12 }, (_, index) => app(`App${index}`));
    const usage = Object.fromEntries(many.map((row, index) => [row.package, index + 1]));
    const groups = arrangeApps(many, [], usage, "");
    expect(groups.mostUsed).toHaveLength(8);
    expect(groups.mostUsed[0].name).toBe("App11");
  });
  it("searches names and package names and hides the rows while searching", () => {
    const groups = arrangeApps(apps, ["com.example.notes"], { "com.example.maps": 3 }, "  MA ");
    expect(groups).toEqual({ pinned: [], mostUsed: [], all: [app("Maps")] });
    expect(arrangeApps(apps, [], {}, "example.mus").all.map((row) => row.name)).toEqual(["Music"]);
  });
  it("gives every app a stable colour", () => {
    expect(monogramHue("com.example.maps")).toBe(monogramHue("com.example.maps"));
    expect(monogramHue("com.example.maps")).toBeGreaterThanOrEqual(0);
    expect(monogramHue("com.example.maps")).toBeLessThan(360);
  });
});

function grid(call: ReturnType<typeof vi.fn>, props: Partial<Parameters<typeof AppGrid>[0]> = {}) {
  return render(<AppGrid apps={apps} deviceId={props.deviceId || "phone"} client={{ call } as unknown as Client} icons pinned={[]} usage={{}} disabled={false}
    onOpen={noop} onPin={noop} onShortcut={noop} {...props} />);
}

describe("AppGrid", () => {
  it("fetches icons from the phone for the tiles and shows a letter until one arrives", async () => {
    vi.useFakeTimers();
    try {
      let answers = 0;
      const call = vi.fn(async (_method: string, args: { packages: string[] }) => {
        answers += 1;
        return answers === 1 ? { icons: { "com.example.maps": PNG, "com.example.chat": "javascript:alert(1)" }, pending: ["com.example.notes"] }
          : { icons: { "com.example.notes": PNG }, pending: [], packages: args.packages };
      });
      const { container } = grid(call, { deviceId: "phone-icons" });
      await act(async () => { await vi.advanceTimersByTimeAsync(150); });
      expect(call).toHaveBeenCalledWith("phone.app.icons", { device_id: "phone-icons", packages: apps.map((row) => row.package) });
      const maps = screen.getByRole("button", { name: "Open Maps" });
      expect(maps.querySelector("img")).toHaveAttribute("src", PNG);
      // An unsafe value is never used as an image; that app keeps its initial.
      expect(screen.getByRole("button", { name: "Open Chat" }).querySelector("img")).toBeNull();
      expect(screen.getByRole("button", { name: "Open Chat" })).toHaveTextContent("C");
      // The phone was still sending one icon: asked again shortly after, for that one only.
      await act(async () => { await vi.advanceTimersByTimeAsync(1600); });
      expect(call).toHaveBeenLastCalledWith("phone.app.icons", { device_id: "phone-icons", packages: ["com.example.notes"] });
      expect(screen.getByRole("button", { name: "Open Notes" }).querySelector("img")).toHaveAttribute("src", PNG);
      expect(container.querySelectorAll("img")).toHaveLength(2);
    } finally { vi.useRealTimers(); }
  });
  it("asks for no icons when the phone cannot send them", async () => {
    vi.useFakeTimers();
    try {
      const call = vi.fn();
      grid(call, { icons: false, deviceId: "phone-noicons" });
      await act(async () => { await vi.advanceTimersByTimeAsync(500); });
      expect(call).not.toHaveBeenCalled();
      expect(screen.getByRole("button", { name: "Open Maps" })).toHaveTextContent("M");
    } finally { vi.useRealTimers(); }
  });
  it("shows Pinned and Most used rows above all apps, and searches", () => {
    const onOpen = vi.fn();
    grid(vi.fn(async () => ({ icons: {}, pending: [] })), { pinned: ["com.example.notes"], usage: { "com.example.maps": 4 }, onOpen, icons: false });
    expect(within(screen.getByRole("list", { name: "Pinned apps" })).getAllByRole("button", { name: /^Open/ }).map((b) => b.getAttribute("aria-label"))).toEqual(["Open Notes"]);
    expect(within(screen.getByRole("list", { name: "Most used apps" })).getByRole("button", { name: "Open Maps" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "All apps" })).toBeVisible();
    fireEvent.click(within(screen.getByRole("list", { name: "Most used apps" })).getByRole("button", { name: "Open Maps" }));
    expect(onOpen).toHaveBeenCalledWith(app("Maps"));
    fireEvent.change(screen.getByLabelText("Find a phone app"), { target: { value: "zzz" } });
    expect(screen.queryByRole("list", { name: "Pinned apps" })).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent("No apps match “zzz”.");
  });
  it("pins and unpins from the tile's menu", async () => {
    const onPin = vi.fn();
    grid(vi.fn(), { pinned: ["com.example.notes"], onPin, icons: false });
    fireEvent.contextMenu(within(screen.getByRole("list", { name: "All apps" })).getByRole("button", { name: "Open Maps" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Pin to the top" }));
    expect(onPin).toHaveBeenCalledWith(app("Maps"), true);
    fireEvent.contextMenu(within(screen.getByRole("list", { name: "Pinned apps" })).getByRole("button", { name: "Open Notes" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Unpin" }));
    expect(onPin).toHaveBeenCalledWith(app("Notes"), false);
  });
  it("disables the tiles while the phone is offline", () => {
    grid(vi.fn(), { disabled: true, icons: false });
    expect(screen.getByRole("button", { name: "Open Maps" })).toBeDisabled();
  });
});

describe("Live indicator", () => {
  it("counts only a live camera or phone screen", () => {
    expect(liveSources({})).toEqual([]);
    expect(liveSources({ phone_screen: { state: "waiting" } as never })).toEqual([]);
    expect(liveSources({ camera: { running: false, local_state: "live" } as never, phone_screen: { state: "live" } as never })).toEqual(["camera", "screen"]);
    expect(liveSources({ camera: { running: true } as never })).toEqual(["camera"]);
    expect(liveLabel(["screen"])).toBe("Phone screen is live");
    expect(liveLabel(["camera", "screen"])).toBe("Camera and phone screen are live");
  });
  it("renders a red Live badge with an accessible name", () => {
    render(<LiveBadge title="Camera is live" />);
    const badge = screen.getByRole("status", { name: "Camera is live" });
    expect(badge).toHaveClass("live-badge");
    expect(badge).toHaveTextContent("Live");
  });
});
