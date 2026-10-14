// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from "react";
import type { Client, WeekSummary } from "./types";
import { Action } from "./ui";
import { Button } from "@/components/ui/button";
import { Disclosure } from "@/components/ui/disclosure";

const screens: Record<string, string> = { phone: "Phone", cloud: "Cloud", settings: "Settings", messages: "Messages", photos: "Photos", calls: "Calls", files: "Files", apps: "Apps" };

/** A personal weekly summary; calculated on this computer when opened and never sent. */
export function YourWeek({ enabled, client }: { enabled?: boolean; client: Client }) {
  const [week, setWeek] = useState<WeekSummary | null>(null);
  const [error, setError] = useState("");
  const [confirming, setConfirming] = useState(false);
  if (enabled === false) return null;
  async function load() {
    try { setWeek(await client.call<WeekSummary>("insights.week")); setError(""); }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
  }
  return <Disclosure summary="Your week" className="[&_b]:text-foreground" onToggle={(event) => { if ((event.currentTarget as HTMLDetailsElement).open) void load(); }}>
    <p className="m-0">Worked out on this computer from the last seven days. It's never sent anywhere.</p>
    {error && <p role="alert" className="inline-error m-0">{error}</p>}
    {week?.enabled && <>
      {week.actions === 0 && week.people.length === 0 ? <p>Nothing yet this week. Use Saiph for a few days and check back.</p> : <>
        <p><b>{week.actions}</b> things done with Saiph{week.busiest_day ? <>, most on <b>{week.busiest_day}</b></> : null}{week.screen ? <>; you opened <b>{screens[week.screen] || week.screen}</b> the most</> : null}.</p>
        {week.top.length > 0 && <ul className="m-0 grid list-none gap-1 p-0 [&_li]:flex [&_li]:items-baseline [&_li]:justify-between [&_li]:gap-3 [&_li]:border-b [&_li]:border-border [&_li]:py-1.5" aria-label="What you used most">{week.top.map((item) =>
          <li key={item.feature}><span>{item.label}</span><b>{item.count}</b></li>)}</ul>}
        {week.people.length > 0 && <>
          <h3 className="m-0 mt-2 text-[13px] font-semibold text-foreground">People you texted most</h3>
          <ul className="m-0 grid list-none gap-1 p-0 [&_li]:flex [&_li]:items-baseline [&_li]:gap-3 [&_li]:border-b [&_li]:border-border [&_li]:py-1.5 [&_span]:flex-1" aria-label="People you texted most">{week.people.map((person) =>
            <li key={person.name}><span>{person.name}</span><b>{person.total}</b><small>{person.sent} sent · {person.received} received</small></li>)}</ul>
        </>}
      </>}
      {/* Clearing cannot be undone, so it asks once. Turning the summary off lives in its setting beside this. */}
      <div className="flex flex-wrap items-center gap-2">
        {confirming
          ? <>
              <span className="text-[12.5px] text-foreground">Clear this week's summary? This can't be undone.</span>
              <Action variant="destructive" size="sm" run={async () => { await client.call("insights.clear"); setConfirming(false); await load(); }}>Clear</Action>
              <Button variant="secondary" size="sm" onClick={() => setConfirming(false)}>Keep</Button>
            </>
          : <Button variant="secondary" size="sm" onClick={() => setConfirming(true)}>Clear this week</Button>}
      </div>
    </>}
  </Disclosure>;
}
