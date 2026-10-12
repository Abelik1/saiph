// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import {
  Action,
  Form,
  HeadsUp,
  Markdown,
  ReminderProgress,
  Ring,
  briefDuration,
  reminderStatus,
} from "./ui";
import type { Reminder } from "./types";

const breakReminder = (payload: Record<string, number | boolean | string>) =>
  ({
    id: "b",
    title: "Stand up",
    kind: "break",
    due_at: null,
    status: "active",
    recurrence: null,
    attention: "urgent",
    payload: { work_seconds: 3000, break_seconds: 600, ...payload },
  }) as Reminder;

describe("workflow feedback", () => {
  it("secondary actions never accidentally submit the enclosing form", async () => {
    const save = vi.fn(),
      browse = vi.fn().mockResolvedValue({});
    render(
      <Form submit={save}>
        <Action run={browse}>Browse</Action>
        <button>Save settings</button>
      </Form>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Browse" }));
    await waitFor(() => expect(browse).toHaveBeenCalledOnce());
    expect(save).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Browse" })).toHaveAttribute(
      "type",
      "button",
    );
  });
  it("displays a backend failure and permits retry", async () => {
    const run = vi
      .fn()
      .mockRejectedValueOnce(new Error("Connection unavailable"))
      .mockResolvedValueOnce({});
    render(<Action run={run}>Save</Action>);
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Connection unavailable",
    );
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(screen.queryByRole("alert")).not.toBeInTheDocument(),
    );
    expect(run).toHaveBeenCalledTimes(2);
  });
  it("disables a form during persistence and reports failure", async () => {
    render(
      <Form
        submit={async () => {
          throw new Error("Folder unavailable");
        }}
      >
        <input aria-label="Folder" />
        <button>Submit</button>
      </Form>,
    );
    fireEvent.submit(
      screen.getByRole("button", { name: "Submit" }).closest("form")!,
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Folder unavailable",
    );
    expect(screen.getByLabelText("Folder")).not.toBeDisabled();
  });
  it("reports remaining time on the progress ring, not just a drawn arc", () => {
    render(
      <Ring
        fraction={0.75}
        label={briefDuration(900)}
        caption="15m 00s of active work before your next break."
      />,
    );
    const ring = screen.getByRole("progressbar");
    expect(ring).toHaveAttribute("aria-valuenow", "75");
    expect(ring).toHaveAccessibleName(
      "15m 00s of active work before your next break.",
    );
    expect(screen.getByText("15m")).toBeVisible();
  });
  it("keeps a clamped early-warning value selectable instead of blanking it", () => {
    const change = vi.fn();
    render(<HeadsUp value={4} change={change} />);
    expect(screen.getByLabelText("Early warning")).toHaveValue("4");
    fireEvent.change(screen.getByLabelText("Early warning"), {
      target: { value: "5" },
    });
    expect(change).toHaveBeenCalledWith(5);
  });
  it("shows the idle countdown once the break detector sees you away", () => {
    const away = breakReminder({ idle_seconds: 134, active_seconds: 2000 });
    render(<ReminderProgress item={away} now={Date.now()} />);
    expect(screen.getByRole("progressbar")).toHaveAccessibleName(
      "Away 2m 14s of 10m 00s needed to reset this break.",
    );
    expect(reminderStatus(away, Date.now())).toBe(
      "Away 2m 14s of 10m 00s needed to reset",
    );
  });
  it("reports remaining work while you are still at the keyboard", () => {
    const working = breakReminder({ idle_seconds: 3, active_seconds: 2400 });
    expect(reminderStatus(working, Date.now())).toBe(
      "10m 00s of active work before your next break",
    );
    const overdue = breakReminder({ idle_seconds: 0, due: true });
    expect(reminderStatus(overdue, Date.now())).toBe(
      "Break due now — you are still at the keyboard",
    );
  });
  it("renders useful Markdown while suppressing embedded images and raw HTML", () => {
    render(
      <Markdown
        text={
          "## Decisions\nUse **CUDA**.\n\n<img src='https://tracker.test/pixel'>\n\n![tracking](https://tracker.test/x)"
        }
      />,
    );
    expect(screen.getByRole("heading", { name: "Decisions" })).toBeVisible();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByText("CUDA")).toBeVisible();
  });
});
