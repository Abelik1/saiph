// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState, type CSSProperties, type ReactNode } from "react";
import { Bell, Copy, ExternalLink, MessageSquare, X } from "lucide-react";
import type { Client, PhoneNotification } from "./types";
import { Action, Form } from "./ui";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

/** A notification from either connection. Hub rows carry the phone's package, actions and reply key;
 * Saiph Cloud rows carry the app name, title, text and time, plus actions and a reply key from phones that offer them. */
export type NotificationRow = Pick<PhoneNotification, "id" | "app" | "title" | "text"> & Partial<Pick<PhoneNotification, "package" | "timestamp" | "actions" | "reply_key" | "code">>;

const TINTS = 5;
/** Phones do not send app icons yet, so each app gets a stable tint and its initials. */
export function appTint(key: string) {
  let hash = 0;
  for (const char of key) hash = (hash * 31 + (char.codePointAt(0) || 0)) >>> 0;
  return (hash % TINTS) + 1;
}
export function appInitials(app: string) {
  const words = app.trim().split(/[\s._-]+/).filter(Boolean);
  const first = (word?: string) => (word ? Array.from(word)[0] : "") || "";
  const letters = words.length > 1 ? first(words[0]) + first(words[1]) : Array.from(words[0] || "").slice(0, 2).join("");
  return letters.toUpperCase() || "?";
}

/** "Just now", "2 min ago", "3 h ago", "Yesterday", then the date. Times are milliseconds. */
export function relativeTime(timestamp: number | undefined, now = Date.now()) {
  if (!timestamp || timestamp <= 0) return "";
  const seconds = Math.max(0, (now - timestamp) / 1000);
  if (seconds < 45) return "Just now";
  if (seconds < 3600) return Math.max(1, Math.round(seconds / 60)) + " min ago";
  if (seconds < 86400) return Math.floor(seconds / 3600) + " h ago";
  if (seconds < 172800) return "Yesterday";
  const date = new Date(timestamp);
  return date.toLocaleDateString(undefined, new Date(now).getFullYear() === date.getFullYear() ? { day: "numeric", month: "short" } : { day: "numeric", month: "short", year: "numeric" });
}

/** Re-renders relative times once a minute; nothing runs while the list is empty. */
function useMinuteClock(active: boolean) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 60_000);
    return () => window.clearInterval(timer);
  }, [active]);
  return now;
}

/** The app's tile: its initials on its tint, the size of a list icon. */
export function AppTile({ app, appKey, className }: { app: string; appKey?: string; className?: string }) {
  const style = { "--tile": `var(--app-tint-${appTint(appKey || app)})` } as CSSProperties;
  return <span aria-hidden="true" data-testid="app-tile" style={style}
    className={cn("flex size-9 shrink-0 select-none items-center justify-center rounded-[10px] border border-[color-mix(in_srgb,var(--tile)_32%,var(--card))] bg-[color-mix(in_srgb,var(--tile)_18%,var(--card))] text-[12.5px] font-semibold tracking-[0.02em] text-[var(--tile)]", className)}>
    {appInitials(app)}
  </span>;
}

function When({ timestamp, now, className }: { timestamp?: number; now: number; className?: string }) {
  const label = relativeTime(timestamp, now);
  if (!label) return null;
  return <time className={cn("shrink-0 text-[11.5px] text-muted-foreground tabular", className)} dateTime={new Date(timestamp!).toISOString()} title={new Date(timestamp!).toLocaleString()}>{label}</time>;
}

const LONG = 140;

/** Title, clamped body and the notification's own actions. Used alone or inside an app's group. */
/** How a list acts on its rows: the Hub's `phone.notification` or Saiph Cloud's `hosted.notification`, and whether Open works. */
type Commands = { method: string; open: boolean };
const HUB: Commands = { method: "phone.notification", open: true };

function NotificationBody({ row, client, online, now, dismiss, showApp, commands = HUB }: { row: NotificationRow; client?: Client; online: boolean; now: number; dismiss: () => unknown; showApp: boolean; commands?: Commands }) {
  const [expanded, setExpanded] = useState(false);
  const [replying, setReplying] = useState(false);
  const [reply, setReply] = useState("");
  const [sent, setSent] = useState(false);
  const command = (operation: string, extra = {}) => client!.call(commands.method, { id: row.id, operation, ...extra });
  const long = row.text.length > LONG || row.text.split("\n").length > 3;
  const actions = row.actions || [];
  return <div className="grid min-w-0 flex-1 gap-1">
    <div className={cn("flex min-w-0 gap-2", showApp ? "items-center" : "items-start")}>
      {showApp
        ? <span className="min-w-0 flex-1 truncate text-[12px] font-medium text-muted-foreground">{row.app}</span>
        : <h4 className="m-0 min-w-0 flex-1 pt-0.5 text-[13px] font-semibold leading-snug [overflow-wrap:anywhere] line-clamp-2">{row.title || row.app}</h4>}
      <When timestamp={row.timestamp} now={now} className={showApp ? undefined : "pt-0.5"} />
      <span className="-my-1 -mr-1.5 flex shrink-0 items-center">
        {client && commands.open && <Action variant="ghost" size="icon-sm" title="Open on phone" ariaLabel={"Open " + (row.title || row.app) + " on phone"} disabled={!online} run={() => command("open")}><ExternalLink /></Action>}
        <Action variant="ghost" size="icon-sm" title="Dismiss on all devices" ariaLabel={"Dismiss " + (row.title || row.app)} disabled={!online} run={async () => { await dismiss(); }}><X /></Action>
      </span>
    </div>
    {showApp && row.title && <h3 className="m-0 text-[13.5px] font-semibold leading-snug [overflow-wrap:anywhere] line-clamp-2">{row.title}</h3>}
    {row.text && <p className={cn("m-0 whitespace-pre-wrap text-[12.5px] leading-relaxed text-muted-foreground [overflow-wrap:anywhere]", !expanded && "line-clamp-3")}>{row.text}</p>}
    {long && <Button variant="link" className="h-auto justify-self-start p-0 text-[12px]" aria-expanded={expanded} onClick={() => setExpanded((value) => !value)}>{expanded ? "Show less" : "Show more"}</Button>}
    {(row.code || actions.length > 0 || (client && row.reply_key && !replying)) && <div className="flex flex-wrap gap-1.5 pt-1">
      {row.code && client && <Action variant="tonal" size="sm" run={() => client.call("phone.code.copy", { id: row.id })}><Copy />Copy code {row.code}</Action>}
      {client && actions.map((action) => <Action key={action.index} variant="tonal" size="sm" disabled={!online} run={() => command("action", { index: action.index })}>{action.label}</Action>)}
      {client && row.reply_key && !replying && <Button variant="tonal" size="sm" disabled={!online} onClick={() => setReplying(true)}><MessageSquare />Reply</Button>}
    </div>}
    {client && row.reply_key && replying && <Form className="grid gap-1.5 pt-1" submit={async () => { await command("reply", { reply_key: row.reply_key, text: reply }); setReply(""); setSent(true); }}>
      <div className="flex gap-2">
        <Input autoFocus aria-label={"Reply to " + row.title} placeholder={"Reply to " + row.title} value={reply} maxLength={4096} className="h-9"
          onChange={(e) => { setReply(e.target.value); setSent(false); }} disabled={!online}
          onKeyDown={(e) => { if (e.key === "Escape" && !reply) setReplying(false); }} />
        <Button type="submit" variant="tonal" size="icon-sm" className="size-9" aria-label="Send reply" title="Send reply" disabled={!online || !reply.trim()}><MessageSquare /></Button>
      </div>
      {sent && <small role="status" className="text-[12px] text-status-on">Reply queued for your phone.</small>}
    </Form>}
  </div>;
}

/** One notification as a card: the app's tile, its name and time, the title and a clamped body. */
export function NotificationCard({ row, client, online, now = Date.now(), dismiss, commands }: { row: NotificationRow; client?: Client; online: boolean; now?: number; dismiss: () => unknown; commands?: Commands }) {
  return <article aria-label={`${row.app}: ${row.title}`} className="flex gap-3 rounded-[12px] border border-border bg-field/50 p-3">
    <AppTile app={row.app} appKey={row.package} />
    <NotificationBody row={row} client={client} online={online} now={now} dismiss={dismiss} showApp commands={commands} />
  </article>;
}

type Group = { key: string; app: string; rows: NotificationRow[] };
/** Groups by app (package when the phone sends one), newest app first, newest first within it. */
export function groupByApp(rows: NotificationRow[]): Group[] {
  const sorted = [...rows].sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0));
  const groups = new Map<string, Group>();
  for (const row of sorted) {
    const key = row.package && row.package !== "unknown" ? row.package : row.app;
    const group = groups.get(key) || { key, app: row.app, rows: [] };
    group.rows.push(row);
    groups.set(key, group);
  }
  return [...groups.values()];
}

/** Several notifications from one app: one header with the tile, name, count and Clear, then a row each. */
function AppGroup({ group, client, online, now, dismiss, commands }: { group: Group; client?: Client; online: boolean; now: number; dismiss: (ids: string[]) => unknown; commands?: Commands }) {
  return <section aria-label={`${group.app}, ${group.rows.length} notifications`} className="grid rounded-[12px] border border-border bg-field/50">
    <header className="flex items-center gap-3 px-3 pt-3 pb-2">
      <AppTile app={group.app} appKey={group.key} />
      <h3 className="m-0 min-w-0 flex-1 truncate text-[13px] font-semibold">{group.app}</h3>
      <Badge tone="quiet" className="tabular">{group.rows.length}</Badge>
      <Action variant="ghost" size="sm" className="-mr-1 h-7 px-2.5 text-[12px]" ariaLabel={`Clear ${group.app} notifications`} disabled={!online}
        run={async () => { await dismiss(group.rows.map((row) => row.id)); }}>Clear</Action>
    </header>
    {group.rows.map((row) => <article key={row.id} aria-label={`${group.app}: ${row.title}`} className="flex border-t border-border/70 py-2.5 pr-3 pl-4">
      <NotificationBody row={row} client={client} online={online} now={now} dismiss={() => dismiss([row.id])} showApp={false} commands={commands} />
    </article>)}
  </section>;
}

/** The empty notifications list: an icon, what is going on and what to do. */
export function NotificationsEmpty({ title, children }: { title: string; children: ReactNode }) {
  return <div className="grid justify-items-center gap-1.5 px-2 py-8 text-center">
    <span aria-hidden="true" className="mb-1 flex size-11 items-center justify-center rounded-full bg-secondary text-secondary-foreground [&_svg]:size-5"><Bell /></span>
    <h3 className="m-0 text-[14px] font-semibold">{title}</h3>
    <p className="m-0 max-w-[240px] text-[12.5px] leading-relaxed text-muted-foreground">{children}</p>
  </div>;
}

/** The Phone page's notifications: cards, grouped by app when an app has several. Passing `client`
 * enables Open, actions, codes and replies; without it a row offers Dismiss only. Saiph Cloud passes
 * `commands` ("hosted.notification", Open only when the phone offers notification actions). */
export function NotificationList({ rows, client, online, dismiss, empty, commands }: { rows: NotificationRow[]; client?: Client; online: boolean; dismiss: (ids: string[]) => unknown; empty: ReactNode; commands?: Commands }) {
  const now = useMinuteClock(rows.length > 0);
  if (!rows.length) return <>{empty}</>;
  return <>{groupByApp(rows).map((group) => group.rows.length === 1
    ? <NotificationCard key={group.key} row={group.rows[0]} client={client} online={online} now={now} dismiss={() => dismiss([group.rows[0].id])} commands={commands} />
    : <AppGroup key={group.key} group={group} client={client} online={online} now={now} dismiss={dismiss} commands={commands} />)}</>;
}
