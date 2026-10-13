// SPDX-License-Identifier: AGPL-3.0-or-later
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { YourWeek } from "./YourWeek";
import type { Client, WeekSummary } from "./types";

const week: WeekSummary = { enabled: true, actions: 9, busiest_day: "Friday", screen: "messages",
  top: [{ feature: "sms_send", label: "Text message sent through the phone", count: 6 }],
  people: [{ name: "Synthetic Ana", sent: 3, received: 4, total: 7 }] };

describe("Your week", () => {
  it("loads only when opened and shows the local summary", async () => {
    const call = vi.fn().mockResolvedValue(week);
    render(<YourWeek enabled client={{ call } as unknown as Client} />);
    expect(call).not.toHaveBeenCalled();
    const details = screen.getByText("Your week").closest("details")!;
    details.open = true;
    fireEvent(details, new Event("toggle"));
    await waitFor(() => expect(call).toHaveBeenCalledWith("insights.week"));
    expect(await screen.findByText(/never sent anywhere/)).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "People you texted most" })).toHaveTextContent("Synthetic Ana");
    expect(screen.getByRole("list", { name: "What you used most" })).toHaveTextContent("Text message sent through the phone");
  });

  it("is hidden when turned off", () => {
    const { container } = render(<YourWeek enabled={false} client={{ call: vi.fn() } as unknown as Client} />);
    expect(container).toBeEmptyDOMElement();
  });
});
