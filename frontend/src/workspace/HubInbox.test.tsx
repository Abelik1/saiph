// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { HubInbox, reminderLabel } from "./HubInbox";
import type { Client, HubItem, State } from "./types";

const item = (overrides: Partial<HubItem>): HubItem => ({
  id: "cal-seminar",
  kind: "proposal",
  source: "schedule-agent",
  title: "Synthetic workshop presentation",
  body: "Your slot, from the seminar schedule email.",
  link: "",
  proposal: {
    calendar: "",
    events: [
      {
        title: "Synthetic workshop presentation",
        start: "2026-11-16T14:00:00+00:00",
        end: "2026-11-16T15:00:00+00:00",
        all_day: false,
        reminders: [1440],
        location: "",
        description: "",
      },
      {
        title: "Email the workshop coordinator about the paper",
        start: "2026-11-02",
        end: null,
        all_day: true,
        reminders: [],
        location: "",
        description: "",
      },
    ],
  },
  status: "new",
  decided_by: null,
  decided_at: null,
  result: "",
  created_at: new Date().toISOString(),
  ...overrides,
});
const stateWith = (items: HubItem[]) =>
  ({ hub_inbox: { items, synced_at: null, error: "" } }) as unknown as State;

describe("hub inbox", () => {
  it("shows the concrete phone action for approval without calendar controls", async () => {
    const call=vi.fn().mockResolvedValue({changed:true});
    render(<HubInbox state={stateWith([item({source:"agent",title:"Reply",proposal:{action:{type:"sms.send"},review:{phone:"Galaxy A55",type:"sms.send",operation:"Send SMS reply",recipients:["+15550000000"],text:"Synthetic outgoing reply"}}})])} client={{call,subscribe:()=>()=>{}} as Client} />);
    expect(screen.getByText("Synthetic outgoing reply")).toBeVisible();
    expect(screen.getByText("To: +15550000000")).toBeVisible();
    expect(screen.queryByRole("button",{name:"Add to calendar"})).toBeNull();
    fireEvent.click(screen.getByRole("button",{name:"Accept"}));
    await waitFor(()=>expect(call).toHaveBeenCalledWith("hub.decide",{id:"cal-seminar",decision:"accept"}));
  });
  it("accepts a calendar suggestion on the hub", async () => {
    const call = vi.fn().mockResolvedValue({ changed: true });
    render(
      <HubInbox
        state={stateWith([item({})])}
        client={{ call, subscribe: () => () => {} } as Client}
      />,
    );
    expect(
      screen.getByText("Email the workshop coordinator about the paper"),
    ).toBeInTheDocument();
    expect(screen.getByText(/reminder 1 day before/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Add to calendar" }));
    await waitFor(() =>
      expect(call).toHaveBeenCalledWith("hub.decide", {
        id: "cal-seminar",
        decision: "accept",
      }),
    );
  });

  it("says who accepted it and that the scout will add it", () => {
    render(
      <HubInbox
        state={stateWith([item({ status: "accepted", decided_by: "Pixel" })])}
        client={{ call: vi.fn(), subscribe: () => () => {} } as Client}
      />,
    );
    expect(
      screen.getByText(/Accepted on Pixel\. The calendar scout adds it/),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Add to calendar" }),
    ).toBeNull();
  });

  it("names reminders in plain words", () => {
    expect(reminderLabel(20160)).toBe("2 weeks before");
    expect(reminderLabel(1440)).toBe("1 day before");
    expect(reminderLabel(90)).toBe("90 minutes before");
    expect(reminderLabel(0)).toBe("at the start");
  });
});
