// SPDX-License-Identifier: AGPL-3.0-or-later
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { YourWeek } from "./YourWeek";
import type { Client, WeekSummary } from "./types";

const week: WeekSummary = { enabled: true, actions: 9, days: [{ date: "2026-10-16", actions: 9 }], busiest_day: "Friday", screen: "messages",
  top: [{ feature: "sms_send", label: "Text message sent through the phone", count: 6 }],
  people: [{ name: "Synthetic Ana", sent: 3, received: 4, total: 7 }] };

describe("Your week", () => {
  it("shows the local summary without a dropdown", async () => {
    const call = vi.fn().mockResolvedValue(week);
    render(<YourWeek enabled client={{ call } as unknown as Client} />);
    await waitFor(() => expect(call).toHaveBeenCalledWith("insights.week"));
    expect(screen.getByText(/only on this computer/)).toBeInTheDocument();
    expect(screen.getByText("Your week").closest("details")).toBeNull();
    expect(screen.getByRole("list", { name: "People you texted most" })).toHaveTextContent("Synthetic Ana");
    expect(screen.getByRole("list", { name: "Daily activity" })).toHaveTextContent("9");
    expect(screen.getByRole("list", { name: "What you used most" })).toHaveTextContent("Text message sent through the phone");
  });

  it("is hidden when turned off", () => {
    const { container } = render(<YourWeek enabled={false} client={{ call: vi.fn() } as unknown as Client} />);
    expect(container).toBeEmptyDOMElement();
  });
});
