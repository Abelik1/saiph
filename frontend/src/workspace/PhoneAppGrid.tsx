// SPDX-License-Identifier: AGPL-3.0-or-later
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { MoreHorizontal, Pin, PinOff, Search, SquareArrowOutUpRight } from "lucide-react";
import type { Client } from "./types";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

export type PhoneApp = { package: string; name: string; system: boolean };
type IconAnswer = { icons: Record<string, string>; pending: string[] };
const ICON = /^data:image\/(png|webp);base64,[A-Za-z0-9+/]+=*$/;
const MOST_USED = 8;
const BATCH = 60;
const RETRIES = 6;
/** Icons survive tab switches and remounts for this page's lifetime; the computer caches them on disk. */
const iconCache = new Map<string, string>();

/** Pinned first in pin order, then the most opened (at least once), then everything, each without repeats. */
export function arrangeApps(apps: PhoneApp[], pinned: string[], usage: Record<string, number>, query: string) {
  const term = query.trim().toLowerCase();
  if (term) return { pinned: [], mostUsed: [], all: apps.filter((app) => app.name.toLowerCase().includes(term) || app.package.toLowerCase().includes(term)) };
  const byPackage = new Map(apps.map((app) => [app.package, app]));
  const pins = pinned.map((name) => byPackage.get(name)).filter((app): app is PhoneApp => Boolean(app));
  const mostUsed = apps.filter((app) => (usage[app.package] || 0) > 0 && !pinned.includes(app.package))
    .sort((a, b) => (usage[b.package] || 0) - (usage[a.package] || 0) || a.name.localeCompare(b.name)).slice(0, MOST_USED);
  return { pinned: pins, mostUsed, all: apps };
}

/** A stable hue turn for an app without an icon, from its package name. */
export function monogramHue(packageName: string): number {
  let hash = 0;
  for (const c of packageName) hash = (hash * 31 + c.charCodeAt(0)) >>> 0;
  return hash % 360;
}

/** Asks the computer for icons of tiles as they scroll into view; the computer asks the phone in small pages. */
function useAppIcons(client: Client, deviceId: string, enabled: boolean) {
  const [, setVersion] = useState(0);
  const wanted = useRef(new Set<string>());
  const tries = useRef(new Map<string, number>());
  const timer = useRef<number | undefined>(undefined);
  const flush = useCallback(async () => {
    timer.current = undefined;
    const batch = [...wanted.current].slice(0, BATCH);
    batch.forEach((name) => wanted.current.delete(name));
    if (!batch.length) return;
    let answer: IconAnswer;
    try { answer = await client.call<IconAnswer>("phone.app.icons", { device_id: deviceId, packages: batch }); }
    catch { return; }
    let changed = false;
    for (const [name, uri] of Object.entries(answer.icons || {})) {
      if (batch.includes(name) && typeof uri === "string" && uri.length <= 20_000 && ICON.test(uri) && iconCache.get(`${deviceId}:${name}`) !== uri) {
        iconCache.set(`${deviceId}:${name}`, uri); changed = true;
      }
    }
    if (changed) setVersion((value) => value + 1);
    // The phone answers a moment later over Saiph Cloud: ask again for what is still on its way.
    const retry = (answer.pending || []).filter((name) => batch.includes(name) && (tries.current.get(name) || 0) < RETRIES);
    retry.forEach((name) => { tries.current.set(name, (tries.current.get(name) || 0) + 1); wanted.current.add(name); });
    if (wanted.current.size && timer.current === undefined) timer.current = window.setTimeout(() => void flush(), retry.length ? 1500 : 60);
  }, [client, deviceId]);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const want = useCallback((name: string) => {
    if (!enabled || tries.current.has(name) || iconCache.has(`${deviceId}:${name}`)) return;
    tries.current.set(name, 0);
    wanted.current.add(name);
    if (timer.current === undefined) timer.current = window.setTimeout(() => void flush(), 100);
  }, [enabled, flush, deviceId]);
  const icon = useCallback((name: string) => iconCache.get(`${deviceId}:${name}`), [deviceId]);
  return { want, icon };
}

function AppIcon({ app, src }: { app: PhoneApp; src?: string }) {
  const [broken, setBroken] = useState(false);
  if (src && !broken) return <img src={src} alt="" draggable={false} onError={() => setBroken(true)}
    className="size-12 shrink-0 rounded-[12px] object-contain select-none" />;
  const letter = Array.from(app.name.trim())[0]?.toUpperCase() || "?";
  const turn = monogramHue(app.package);
  return <span aria-hidden="true" className="grid size-12 shrink-0 place-items-center rounded-[12px] text-lg font-semibold text-[var(--tile-monogram-foreground)] select-none"
    style={{ background: `linear-gradient(150deg, oklch(from var(--primary) 0.62 0.13 calc(h + ${turn})), oklch(from var(--primary) 0.45 0.11 calc(h + ${turn + 40})))` }}>{letter}</span>;
}

function Tile({ app, icon, pinned, disabled, shortcut, onOpen, onPin, onShortcut, onVisible }: {
  app: PhoneApp; icon?: string; pinned: boolean; disabled: boolean; shortcut: string;
  onOpen: () => void; onPin: (pinned: boolean) => void; onShortcut: () => void; onVisible: () => void;
}) {
  const element = useRef<HTMLLIElement>(null);
  const [menu, setMenu] = useState(false);
  useEffect(() => {
    const node = element.current;
    if (!node || typeof IntersectionObserver === "undefined") { onVisible(); return; }
    const observer = new IntersectionObserver((entries) => { if (entries.some((entry) => entry.isIntersecting)) { onVisible(); observer.disconnect(); } }, { rootMargin: "200px" });
    observer.observe(node);
    return () => observer.disconnect();
  }, [onVisible]);
  return <li ref={element} className="app-tile-cell group relative" onContextMenu={(event) => { event.preventDefault(); setMenu(true); }}>
    <button type="button" className="app-tile" aria-label={"Open " + app.name} title={app.name} disabled={disabled} onClick={onOpen}>
      <AppIcon app={app} src={icon} />
      <span className="line-clamp-2 w-full text-center text-[12px] leading-tight [overflow-wrap:anywhere]">{app.name}</span>
      {pinned && <Pin aria-label="Pinned" className="absolute top-1.5 left-1.5 size-3 text-primary" />}
    </button>
    <DropdownMenu open={menu} onOpenChange={setMenu}>
      <DropdownMenuTrigger asChild>
        <button type="button" className="app-tile-more" aria-label={"More for " + app.name} title="More"><MoreHorizontal /></button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-52">
        <DropdownMenuItem onSelect={() => onPin(!pinned)}>{pinned ? <><PinOff />Unpin</> : <><Pin />Pin to the top</>}</DropdownMenuItem>
        <DropdownMenuItem onSelect={onShortcut}><SquareArrowOutUpRight />{shortcut}</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  </li>;
}

/**
 * The phone's apps as a grid of icons: Pinned and Most used rows above all apps, and a search box.
 * Icons come from the phone (Saiph Cloud, end-to-end encrypted); without one an app shows its initial.
 */
export function AppGrid({ apps, deviceId, client, icons: iconsEnabled, pinned, usage, disabled, onOpen, onPin, onShortcut }: {
  apps: PhoneApp[]; deviceId: string; client: Client; icons: boolean; pinned: string[]; usage: Record<string, number>; disabled: boolean;
  onOpen: (app: PhoneApp) => void; onPin: (app: PhoneApp, pinned: boolean) => void; onShortcut: (app: PhoneApp) => void;
}) {
  const [query, setQuery] = useState("");
  const findId = useId();
  const { want, icon } = useAppIcons(client, deviceId, iconsEnabled);
  const groups = useMemo(() => arrangeApps(apps, pinned, usage, query), [apps, pinned, usage, query]);
  const shortcut = typeof navigator !== "undefined" && /Windows/i.test(navigator.userAgent) ? "Add to Start menu" : "Add to apps menu";
  const visible = useRef(new Map<string, () => void>());
  const onVisible = (name: string) => {
    let handler = visible.current.get(name);
    if (!handler) { handler = () => want(name); visible.current.set(name, handler); }
    return handler;
  };
  useEffect(() => { visible.current.clear(); }, [want]);
  const grid = (rows: PhoneApp[], label: string) => <ul className="app-grid" aria-label={label}>
    {rows.map((app) => <Tile key={app.package} app={app} icon={icon(app.package)} pinned={pinned.includes(app.package)} disabled={disabled}
      shortcut={shortcut} onOpen={() => onOpen(app)} onPin={(value) => onPin(app, value)} onShortcut={() => onShortcut(app)} onVisible={onVisible(app.package)} />)}
  </ul>;
  const heading = (text: string) => <h3 className="m-0 mb-2 text-[12.5px] font-semibold tracking-wide text-muted-foreground">{text}</h3>;
  return <div className="grid gap-5">
    <Field label="Find an app" htmlFor={findId} className="max-w-80">
      <div className="relative"><Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input id={findId} type="search" aria-label="Find a phone app" value={query} onChange={(event) => setQuery(event.target.value)} className="pl-9" /></div>
    </Field>
    {groups.pinned.length > 0 && <section>{heading("Pinned")}{grid(groups.pinned, "Pinned apps")}</section>}
    {groups.mostUsed.length > 0 && <section>{heading("Most used")}{grid(groups.mostUsed, "Most used apps")}</section>}
    <section>
      {!query.trim() && (groups.pinned.length > 0 || groups.mostUsed.length > 0) && heading("All apps")}
      {groups.all.length ? grid(groups.all, query.trim() ? "Matching apps" : "All apps")
        : <p className={cn("m-0 text-[12.5px] text-muted-foreground")} role="status">No apps match “{query.trim()}”.</p>}
    </section>
  </div>;
}
