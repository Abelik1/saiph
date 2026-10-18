// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from "react";
import type { Client, WeekSummary } from "./types";
import { Action } from "./ui";
import { Button } from "@/components/ui/button";
import { PreferenceCard } from "./PreferenceCard";

const screens: Record<string, string> = { phone: "Phone", cloud: "Cloud", settings: "Settings", messages: "Messages", photos: "Photos", calls: "Calls", files: "Files", apps: "Apps" };

/** A personal weekly summary, calculated on this computer and never sent. */
export function YourWeek({ enabled, client }: { enabled?: boolean; client: Client }) {
  const [week, setWeek] = useState<WeekSummary | null>(null);
  const [error, setError] = useState("");
  const [confirming, setConfirming] = useState(false);
  useEffect(() => {
    if (!enabled) { setWeek(null); setConfirming(false); return; }
    let active = true;
    client.call<WeekSummary>("insights.week").then(value => { if (active) { setWeek(value); setError(""); } })
      .catch(reason => { if (active) setError(reason instanceof Error ? reason.message : String(reason)); });
    return () => { active = false; };
  }, [client, enabled]);
  if (!enabled) return null;
  async function load() {
    try { setWeek(await client.call<WeekSummary>("insights.week")); setError(""); }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
  }
  const days = week?.days || [];
  const maximum = Math.max(1, ...days.map(day => day.actions));
  return <PreferenceCard title="Your week" subtitle="Last seven days · only on this computer">
    {error && <p role="alert" className="inline-error m-0">{error}</p>}
    {!week && !error && <p role="status">Loading your week…</p>}
    {error && <div><Action run={load}>Try again</Action></div>}
    {week?.enabled && <>
      {week.actions === 0 && week.people.length === 0 ? <p>Nothing yet this week. Use Saiph for a few days and check back.</p> : <>
        <dl className="m-0 grid grid-cols-3 gap-3 [&>div]:rounded-xl [&>div]:bg-muted/40 [&>div]:p-3 [&_dt]:text-xs [&_dt]:text-muted-foreground [&_dd]:m-0 [&_dd]:mt-2 [&_dd]:text-lg [&_dd]:font-semibold">
          <div><dt>Actions</dt><dd>{week.actions}</dd></div>
          <div><dt>Busiest day</dt><dd>{week.busiest_day || "—"}</dd></div>
          <div><dt>Most opened</dt><dd>{week.screen ? screens[week.screen] || week.screen : "—"}</dd></div>
        </dl>
        {days.length > 0 && <ol className="m-0 grid list-none grid-cols-7 gap-2 p-0" aria-label="Daily activity">{days.map(day => {
          const label = new Date(day.date + "T12:00:00").toLocaleDateString(undefined, { weekday: "short" });
          return <li key={day.date} className="grid gap-2 text-center" aria-label={`${day.date}: ${day.actions} actions`}>
            <div className="flex h-20 items-end rounded-md bg-muted/30"><div className="w-full rounded-md bg-primary/70" style={{ height: `${day.actions / maximum * 100}%` }} /></div>
            <span className="text-xs text-muted-foreground">{label}</span><span className="text-xs">{day.actions}</span>
          </li>;
        })}</ol>}
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
  </PreferenceCard>;
}
