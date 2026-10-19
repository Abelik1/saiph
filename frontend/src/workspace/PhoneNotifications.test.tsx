// SPDX-License-Identifier: AGPL-3.0-or-later
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AppTile, NotificationCard, NotificationList, NotificationsEmpty, appInitials, appTint, groupByApp, relativeTime, type NotificationRow } from "./PhoneNotifications";
import type { Client } from "./types";

const NOW = Date.UTC(2026, 9, 18, 12, 0, 0);
const row = (id: string, changes: Partial<NotificationRow> = {}): NotificationRow =>
  ({ id, app: "Messages", package: "com.example.messages", title: "Title " + id, text: "Body " + id, timestamp: NOW - 120_000, actions: [], ...changes });
const client = (call = vi.fn().mockResolvedValue({})) => ({ call } as unknown as Client);

describe("Notification details", () => {
  it("says how long ago, in words people use", () => {
    expect(relativeTime(NOW - 10_000, NOW)).toBe("Just now");
    expect(relativeTime(NOW - 120_000, NOW)).toBe("2 min ago");
    expect(relativeTime(NOW - 3 * 3600_000, NOW)).toBe("3 h ago");
    expect(relativeTime(NOW - 30 * 3600_000, NOW)).toBe("Yesterday");
    expect(relativeTime(NOW - 9 * 86400_000, NOW)).toMatch(/9/);
    // A phone clock slightly ahead is not "in the future".
    expect(relativeTime(NOW + 30_000, NOW)).toBe("Just now");
    expect(relativeTime(0, NOW)).toBe("");
    expect(relativeTime(undefined, NOW)).toBe("");
  });

  it("gives every app stable initials and one of the token tints", () => {
    expect(appInitials("Messages")).toBe("ME");
    expect(appInitials("Google Maps")).toBe("GM");
    expect(appInitials("  ")).toBe("?");
    expect(appInitials("élan vital")).toBe("ÉV");
    expect(appTint("com.example.messages")).toBe(appTint("com.example.messages"));
    for (const name of ["a", "b", "com.whatsapp", "Gmail", "📷 Camera"]) expect([1, 2, 3, 4, 5]).toContain(appTint(name));
    render(<AppTile app="Gmail" appKey="com.google.android.gm" />);
    const tile = screen.getByTestId("app-tile");
    expect(tile).toHaveAttribute("aria-hidden", "true");
    expect(tile.style.getPropertyValue("--tile")).toMatch(/^var\(--app-tint-[1-5]\)$/);
    expect(tile).toHaveTextContent("GM");
  });

  it("groups by package, newest app first and newest first inside it", () => {
    const groups = groupByApp([
      row("old", { timestamp: NOW - 600_000 }),
      row("mail", { app: "Gmail", package: "com.google.android.gm", timestamp: NOW - 60_000 }),
      row("new", { timestamp: NOW - 30_000 }),
      // Saiph Cloud rows have no package: the app name groups them.
      row("cloud", { app: "Calendar", package: undefined }),
    ]);
    expect(groups.map((group) => [group.app, group.rows.map((item) => item.id)])).toEqual([
      ["Messages", ["new", "old"]], ["Gmail", ["mail"]], ["Calendar", ["cloud"]],
    ]);
  });
});

describe("Notification card", () => {
  it("shows the app, title, clamped body and time, with a labelled Dismiss", async () => {
    const dismiss = vi.fn();
    const long = "A long synthetic body. ".repeat(12);
    render(<NotificationCard row={row("a", { text: long })} client={client()} online now={NOW} dismiss={dismiss} />);
    const card = screen.getByRole("article", { name: "Messages: Title a" });
    expect(within(card).getByText("Messages")).toBeVisible();
    expect(within(card).getByRole("heading", { name: "Title a" })).toBeVisible();
    expect(within(card).getByText("2 min ago")).toHaveAttribute("datetime", new Date(NOW - 120_000).toISOString());
    const body = within(card).getByText(long.trim(), { exact: false });
    expect(body).toHaveClass("line-clamp-3");
    const more = within(card).getByRole("button", { name: "Show more" });
    expect(more).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(more);
    expect(body).not.toHaveClass("line-clamp-3");
    expect(within(card).getByRole("button", { name: "Show less" })).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(within(card).getByRole("button", { name: "Dismiss Title a" }));
    await waitFor(() => expect(dismiss).toHaveBeenCalledTimes(1));
  });

  it("has no Show more for a short body, and only Dismiss without a Hub client (Saiph Cloud)", () => {
    render(<NotificationCard row={row("a", { reply_key: "r", actions: [{ index: 1, label: "Archive" }] })} online now={NOW} dismiss={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "Show more" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Open/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Archive" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Reply" })).toBeNull();
    expect(screen.getByRole("button", { name: "Dismiss Title a" })).toBeEnabled();
  });

  it("opens, acts and replies through the owning phone, and disables them offline", async () => {
    const call = vi.fn().mockResolvedValue({});
    const notice = row("a", { reply_key: "r", actions: [{ index: 1, label: "Archive" }] });
    const { rerender } = render(<NotificationCard row={notice} client={client(call)} online now={NOW} dismiss={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Open Title a on phone" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("phone.notification", { id: "a", operation: "open" }));
    fireEvent.click(screen.getByRole("button", { name: "Archive" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("phone.notification", { id: "a", operation: "action", index: 1 }));
    rerender(<NotificationCard row={notice} client={client(call)} online={false} now={NOW} dismiss={vi.fn()} />);
    for (const name of ["Open Title a on phone", "Archive", "Reply", "Dismiss Title a"]) expect(screen.getByRole("button", { name })).toBeDisabled();
  });
});

describe("Notification list", () => {
  it("shows a lone notification as a card and several from one app as a group with Clear", async () => {
    const dismiss = vi.fn();
    render(<NotificationList rows={[row("a"), row("b", { timestamp: NOW - 60_000 }), row("m", { app: "Gmail", package: "com.google.android.gm" })]}
      client={client()} online dismiss={dismiss} empty={null} />);
    const group = screen.getByRole("region", { name: "Messages, 2 notifications" });
    expect(within(group).getAllByTestId("app-tile")).toHaveLength(1);
    expect(within(group).getByRole("heading", { name: "Title b" })).toBeVisible();
    fireEvent.click(within(group).getByRole("button", { name: "Clear Messages notifications" }));
    await waitFor(() => expect(dismiss).toHaveBeenCalledWith(["b", "a"]));
    fireEvent.click(within(group).getByRole("button", { name: "Dismiss Title a" }));
    await waitFor(() => expect(dismiss).toHaveBeenCalledWith(["a"]));
    expect(screen.getByRole("article", { name: "Gmail: Title m" })).toBeVisible();
  });

  it("shows the empty state when there is nothing to show", () => {
    render(<NotificationList rows={[]} online dismiss={vi.fn()} empty={<NotificationsEmpty title="All clear">Your phone notifications appear here automatically.</NotificationsEmpty>} />);
    expect(screen.getByRole("heading", { name: "All clear" })).toBeVisible();
    expect(screen.getByText("Your phone notifications appear here automatically.")).toBeVisible();
  });
});
