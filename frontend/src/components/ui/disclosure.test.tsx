// SPDX-License-Identifier: AGPL-3.0-or-later
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { Disclosure } from "./disclosure";

describe("Disclosure", () => {
  it("is a native details/summary pair, so keyboards and screen readers treat it as a disclosure", () => {
    render(<Disclosure summary="Recent device changes" meta={<span>3</span>}><p>Approved Phone</p></Disclosure>);
    const summary = screen.getByText("Recent device changes").closest("summary")!;
    const details = summary.parentElement!;
    expect(details.tagName).toBe("DETAILS");
    expect(details).toHaveAttribute("data-slot", "disclosure");
    // The summary is the first child: that is what makes it the focusable, toggling control.
    expect(details.firstElementChild).toBe(summary);
    expect(summary).toHaveTextContent("Recent device changes3");
    // The chevron is decoration only.
    expect(summary.querySelector(".disclosure-chevron")).toHaveAttribute("aria-hidden", "true");
    expect(details).not.toHaveAttribute("open");
    expect(screen.getByText("Approved Phone")).not.toBeVisible();
  });

  it("is reached with Tab, shows a focus style and toggles on activation", async () => {
    // Browsers turn Enter and Space on a focused summary into a click; jsdom does not, so the
    // keypress itself is checked in the real Qt shell (tests/packaging/desktop_settings_polish.cjs).
    const user = userEvent.setup();
    render(<><button>Before</button><Disclosure summary="Phone details"><p>Hidden detail</p></Disclosure></>);
    const summary = screen.getByText("Phone details").closest("summary")!;
    await user.click(screen.getByRole("button", { name: "Before" }));
    await user.tab();
    expect(summary).toHaveFocus();
    expect(summary.className).toMatch(/focus-visible:/);
    await user.click(summary);
    expect(summary.parentElement).toHaveAttribute("open");
    expect(screen.getByText("Hidden detail")).toBeVisible();
    await user.click(summary);
    expect(summary.parentElement).not.toHaveAttribute("open");
  });

  it("can start open and closes when its summary is clicked", () => {
    render(<Disclosure summary="Open by default" open><p>Shown</p></Disclosure>);
    expect(screen.getByText("Shown")).toBeVisible();
    fireEvent.click(screen.getByText("Open by default"));
    expect(screen.getByText("Open by default").closest("details")).not.toHaveAttribute("open");
  });
});
