// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from "react";
import type { Client, WeekSummary } from "./types";
import { Action } from "./ui";

const screens: Record<string, string> = { phone: "Phone", cloud: "Cloud", settings: "Settings", messages: "Messages", photos: "Photos", calls: "Calls", files: "Files", apps: "Apps" };

/** A personal weekly summary; calculated on this computer when opened and never sent. */
export function YourWeek({ enabled, client }: { enabled?: boolean; client: Client }) {
  const [week, setWeek] = useState<WeekSummary | null>(null);
  const [error, setError] = useState("");
  if (enabled === false) return null;
  async function load() {
    try { setWeek(await client.call<WeekSummary>("insights.week")); setError(""); }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
  }
  return <details className="your-week" onToggle={(event) => { if ((event.currentTarget as HTMLDetailsElement).open) void load(); }}>
    <summary>Your week</summary>
    <p className="muted">Worked out on this computer from the last seven days. It's never sent anywhere.</p>
    {error && <p role="alert">{error}</p>}
    {week?.enabled && <>
      {week.actions === 0 && week.people.length === 0 ? <p>Nothing yet this week. Use Saiph for a few days and check back.</p> : <>
        <p><b>{week.actions}</b> things done with Saiph{week.busiest_day ? <>, most on <b>{week.busiest_day}</b></> : null}{week.screen ? <>; you opened <b>{screens[week.screen] || week.screen}</b> the most</> : null}.</p>
        {week.top.length > 0 && <ul className="your-week-list" aria-label="What you used most">{week.top.map((item) =>
          <li key={item.feature}><span>{item.label}</span><b>{item.count}</b></li>)}</ul>}
        {week.people.length > 0 && <>
          <h3>People you texted most</h3>
          <ul className="your-week-list" aria-label="People you texted most">{week.people.map((person) =>
            <li key={person.name}><span>{person.name}</span><b>{person.total}</b><small>{person.sent} sent · {person.received} received</small></li>)}</ul>
        </>}
      </>}
      <div className="actions">
        <Action className="text-button" run={async () => { await client.call("insights.clear"); await load(); }}>Clear this week</Action>
        <Action className="text-button" run={() => client.call("insights.enable", { enabled: false })}>Turn off Your week</Action>
      </div>
    </>}
  </details>;
}
