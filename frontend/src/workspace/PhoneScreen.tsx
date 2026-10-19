// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useRef, useState } from "react";
import { AppWindow, ArrowLeft, Circle, MonitorSmartphone, Square } from "lucide-react";
import type { Client, PhoneScreenStatus } from "./types";
import { followFrames, showRate } from "./frameFeed";
import { Action } from "./ui";
import { QrImage, validQr, type PairingQrCode } from "./PairingQr";
import { LiveBadge } from "./LiveIndicator";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Item, ItemActions, ItemContent, ItemDescription, ItemMedia, ItemTitle } from "@/components/ui/item";

type ScreenCode = PairingQrCode & { session: string; delivered: boolean };
type Frame = { image: string | null; sequence: number; fps?: number; width?: number; height?: number; shown?: number };
export type ScreenEvent =
  | { t: "tap" | "long"; x: number; y: number }
  | { t: "swipe"; x: number; y: number; x2: number; y2: number; ms: number }
  | { t: "key"; key: "back" | "home" | "recents" | "backspace" | "enter" }
  | { t: "text"; text: string };
const SCALE = 10000;
const MAX_IMAGE = 1_000_000;

/** A pointer position as integers in [0, SCALE] of the phone frame shown with object-contain; null outside it. */
export function framePoint(box: { left: number; top: number; width: number; height: number },
  natural: { width: number; height: number }, clientX: number, clientY: number): { x: number; y: number } | null {
  if (!natural.width || !natural.height || !box.width || !box.height) return null;
  const scale = Math.min(box.width / natural.width, box.height / natural.height);
  const width = natural.width * scale, height = natural.height * scale;
  const x = (clientX - box.left - (box.width - width) / 2) / width;
  const y = (clientY - box.top - (box.height - height) / 2) / height;
  if (x < 0 || x > 1 || y < 0 || y > 1) return null;
  return { x: Math.round(x * SCALE), y: Math.round(y * SCALE) };
}

/** A press becomes a tap, a long press (held 500 ms) or a swipe (moved over 2% of the frame). */
export function gesture(start: { x: number; y: number; at: number }, end: { x: number; y: number; at: number }): ScreenEvent {
  const held = end.at - start.at;
  if (Math.hypot(end.x - start.x, end.y - start.y) < SCALE * 0.02)
    return held >= 500 ? { t: "long", x: start.x, y: start.y } : { t: "tap", x: start.x, y: start.y };
  return { t: "swipe", x: start.x, y: start.y, x2: end.x, y2: end.y, ms: Math.min(3000, Math.max(50, Math.round(held))) };
}

/** Printable text the phone accepts: no control characters, at most 256 characters. */
export function typed(text: string): string {
  return Array.from(text).filter((c) => { const code = c.codePointAt(0) ?? 0; return code >= 32 && code !== 127; }).slice(0, 256).join("");
}

/** The phone's screen over the local network, with mouse and keyboard sent back while it is live. */
export function PhoneScreen({ screen, deviceId, client }: { screen?: PhoneScreenStatus; deviceId?: string; client: Client }) {
  const [code, setCode] = useState<ScreenCode | null>(null);
  const [showQr, setShowQr] = useState(false);
  const [remaining, setRemaining] = useState(120);
  const [resolution, setResolution] = useState("1080p");
  const [fps, setFps] = useState(20);
  const [quality, setQuality] = useState("high");
  const [frame, setFrame] = useState<Frame | null>(null);
  const [notice, setNotice] = useState("");
  const invitation = useRef<string | null>(null);
  const observed = useRef(false);
  const image = useRef<HTMLImageElement>(null);
  const press = useRef<{ x: number; y: number; at: number } | null>(null);
  const buffer = useRef("");
  const flush = useRef<number | undefined>(undefined);
  const wheelAt = useRef(0);
  const live = screen?.state === "live";
  // The desktop app shows a live session in its own window; the page embeds it only without one.
  const windowed = live && (screen?.window === "open" || screen?.window === "closed");
  const waiting = screen?.state === "waiting" || screen?.state === "connecting";
  const activeFps = screen?.fps || 15;
  useEffect(() => () => {
    if (invitation.current) void client.call("screen.cancel_invite", { session: invitation.current }).catch(() => {});
  }, [client]);
  useEffect(() => {
    // The code closes once the phone connects, or when an observed session ends.
    if (live || waiting) observed.current = true;
    if (live || (!waiting && observed.current)) {
      invitation.current = null; setCode(null); setShowQr(false);
      if (!live) observed.current = false;
    }
  }, [live, waiting]);
  // A session started elsewhere (Mirror screen, a pinned app): show its request status and code here.
  useEffect(() => {
    if (!waiting || code) return;
    let cancelled = false;
    void client.call<ScreenCode | Record<string, never>>("screen.invite").then((next) => {
      if (cancelled || !("session" in next) || !validQr(next) || !/^[a-f0-9]{32}$/.test(next.session)) return;
      invitation.current = next.session; observed.current = true;
      setShowQr(!next.delivered); setCode(next);
    }, () => undefined);
    return () => { cancelled = true; };
  }, [client, waiting, code]);
  useEffect(() => {
    if (!code) return;
    const tick = () => setRemaining(Math.max(0, Math.ceil((Date.parse(code.expires_at) - Date.now()) / 1000)));
    tick(); const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, [code]);
  useEffect(() => {
    if (!live || windowed) { setFrame(null); return; }
    // Pushed frames replace the picture directly; React hears about them only
    // for the first picture, a new size, or the once-a-second status line.
    const rate = showRate();
    let reported = 0, size = "";
    const follow = followFrames(client, "screen", (info, _picture, url) => {
      const element = image.current;
      if (element) element.src = url;
      const shown = rate(), now = performance.now(), next = `${info.width}x${info.height}`;
      if (!element || next !== size || now - reported >= 1000) {
        reported = now; size = next;
        setFrame({ image: url, sequence: info.sequence, fps: info.fps, width: info.width, height: info.height, shown });
      }
    }, () => !image.current || image.current.offsetParent !== null);
    if (follow) return follow;
    let cancelled = false;
    let timer: number;
    const poll = async () => {
      const started = performance.now();
      try {
        const next = await client.call<Frame>("screen.frame");
        if (!cancelled) setFrame(typeof next.image === "string" && next.image.length <= MAX_IMAGE
          && next.image.startsWith("data:image/jpeg;base64,") ? next : null);
      } catch { if (!cancelled) setFrame(null); }
      // Start only after completion, so slow reads never overlap or queue up.
      if (!cancelled) timer = window.setTimeout(poll, Math.max(0, 1000 / activeFps - (performance.now() - started)));
    };
    void poll();
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [client, live, windowed, activeFps]);
  const send = (event: ScreenEvent) => {
    void client.call("screen.input", { event }).then(() => setNotice(""), (reason: unknown) => setNotice(reason instanceof Error ? reason.message : String(reason)));
  };
  const point = (event: { clientX: number; clientY: number }) => {
    const element = image.current;
    if (!element) return null;
    return framePoint(element.getBoundingClientRect(), { width: element.naturalWidth || frame?.width || 0, height: element.naturalHeight || frame?.height || 0 },
      event.clientX, event.clientY);
  };
  const queueText = (text: string) => {
    const clean = typed(text);
    if (!clean) return;
    buffer.current = typed(buffer.current + clean);
    window.clearTimeout(flush.current);
    flush.current = window.setTimeout(() => { const value = buffer.current; buffer.current = ""; if (value) send({ t: "text", text: value }); }, 80);
  };
  async function start() {
    observed.current = false;
    const next = await client.call<ScreenCode>("screen.session", { ...(deviceId ? { device_id: deviceId } : {}), resolution, fps, quality });
    if (!validQr(next) || !/^[a-f0-9]{32}$/.test(next.session)) throw new Error("The phone screen code could not be displayed.");
    invitation.current = next.session;
    setRemaining(120); setShowQr(!next.delivered); setCode(next);
  }
  async function stop() {
    await client.call("screen.stop"); invitation.current = null; observed.current = false; setCode(null); setFrame(null);
  }
  const input = Boolean(screen?.input);
  return <div className="grid gap-4" aria-label="Phone screen">
    <Item variant="outline" className={cn("p-3", live && "live-outline")}>
      <ItemMedia><MonitorSmartphone /></ItemMedia>
      <ItemContent>
        <ItemTitle>Phone screen {live && <LiveBadge title="Your phone screen is live on this computer" />}</ItemTitle>
        <ItemDescription>{windowed ? (input ? "Showing in its own window. Click, drag and type there to use your phone; closing the window stops sharing."
          : "Showing in its own window, view only. Closing the window stops sharing.")
          : live ? (input ? "Click, drag and type to use your phone. Esc goes back." : "View only. To control your phone from here, turn on Control from computer in Saiph on your phone.")
          : `See and use your phone ${screen?.window && screen.window !== "unavailable" ? "in its own window" : "here"}. No cable needed: keep both devices on the same Wi-Fi.`}</ItemDescription>
      </ItemContent>
      <ItemActions className="flex-wrap">
        {windowed && <Action variant="tonal" size="sm" run={() => client.call("screen.window")}><AppWindow />Show window</Action>}
        {live || waiting || code ? <Action variant="destructive" size="sm" run={stop}>{live ? "Stop" : "Cancel"}</Action>
          : <Action size="sm" run={start}>Show phone screen</Action>}
      </ItemActions>
    </Item>
    {!live && !waiting && !code && <div className="flex flex-wrap gap-x-5 gap-y-2">
      <fieldset className="grid gap-1"><legend className="text-[12.5px] text-muted-foreground">Resolution</legend><div className="flex gap-1">
        {["720p", "1080p"].map(value => <Button key={value} size="sm" variant={resolution === value ? "tonal" : "ghost"} aria-pressed={resolution === value} onClick={() => setResolution(value)}>{value}</Button>)}
      </div></fieldset>
      <fieldset className="grid gap-1"><legend className="text-[12.5px] text-muted-foreground">Frame rate</legend><div className="flex gap-1">
        {[15, 20, 30].map(value => <Button key={value} size="sm" variant={fps === value ? "tonal" : "ghost"} aria-pressed={fps === value} onClick={() => setFps(value)}>{value} fps</Button>)}
      </div></fieldset>
      <fieldset className="grid gap-1"><legend className="text-[12.5px] text-muted-foreground">Detail</legend><div className="flex gap-1">
        {([["standard", "Standard"], ["high", "High"]] as const).map(([value, label]) => <Button key={value} size="sm" variant={quality === value ? "tonal" : "ghost"} aria-pressed={quality === value} onClick={() => setQuality(value)}>{label}</Button>)}
      </div></fieldset>
    </div>}
    {(code || waiting) && !live && <div className="grid justify-items-center gap-3 text-center">
      {screen?.launch && <p className="m-0 text-sm">Your phone opens the app once you start sharing.</p>}
      {code?.delivered && <p className="m-0 text-sm" role="status">On your phone, tap the Saiph notification, verify it's you and choose Start now.</p>}
      {code && !showQr && <Button size="sm" variant="ghost" onClick={() => setShowQr(true)}>No notification? Show a code to scan</Button>}
      {code && showQr && (remaining > 0 ? <>
        <QrImage modules={code.modules} label="Phone screen QR code" width={220} />
        <p className="m-0 text-sm">On your phone: Saiph → Show phone screen → Scan computer's code.</p>
        <small className="text-muted-foreground" role="timer">Works once · expires in {remaining}s. Keep this code private.</small>
      </> : <p role="status" className="m-0 text-sm">Code expired. Cancel and start again.</p>)}
    </div>}
    {live && !windowed && <div className="grid justify-items-center gap-2">
      <div className="flex gap-1" role="toolbar" aria-label="Phone buttons">
        <Button size="sm" variant="ghost" disabled={!input} aria-label="Back" title="Back (Esc)" onClick={() => send({ t: "key", key: "back" })}><ArrowLeft /></Button>
        <Button size="sm" variant="ghost" disabled={!input} aria-label="Home" title="Home" onClick={() => send({ t: "key", key: "home" })}><Circle /></Button>
        <Button size="sm" variant="ghost" disabled={!input} aria-label="Recent apps" title="Recent apps" onClick={() => send({ t: "key", key: "recents" })}><Square /></Button>
      </div>
      {frame?.image ? <img ref={image} src={frame.image} alt="Your phone's screen" tabIndex={0} draggable={false}
        className="max-h-[70vh] w-auto max-w-full touch-none rounded-lg bg-field object-contain outline-none select-none focus-visible:ring-2 focus-visible:ring-ring"
        onPointerDown={(event) => {
          if (!input) return;
          const at = point(event); if (!at) return;
          event.currentTarget.focus(); event.currentTarget.setPointerCapture?.(event.pointerId);
          press.current = { ...at, at: performance.now() };
        }}
        onPointerUp={(event) => {
          const started = press.current; press.current = null;
          const at = point(event);
          if (!started || !input) return;
          send(gesture(started, { ...(at || started), at: performance.now() }));
        }}
        onPointerCancel={() => { press.current = null; }}
        onWheel={(event) => {
          if (!input || performance.now() - wheelAt.current < 250) return;
          const at = point(event); if (!at) return;
          wheelAt.current = performance.now();
          const step = Math.sign(event.deltaY) * 2500;
          send({ t: "swipe", x: at.x, y: at.y, x2: at.x, y2: Math.min(SCALE, Math.max(0, at.y - step)), ms: 250 });
        }}
        onKeyDown={(event) => {
          if (!input || event.ctrlKey || event.metaKey || event.altKey) return;
          if (event.key === "Escape") { event.preventDefault(); send({ t: "key", key: "back" }); }
          else if (event.key === "Backspace") { event.preventDefault(); send({ t: "key", key: "backspace" }); }
          else if (event.key === "Enter") { event.preventDefault(); send({ t: "key", key: "enter" }); }
          else if (event.key.length === 1 || Array.from(event.key).length === 1) { event.preventDefault(); queueText(event.key); }
        }}
        onPaste={(event) => { if (!input) return; event.preventDefault(); queueText(event.clipboardData.getData("text/plain")); }}
      /> : <p className="m-0 text-sm text-muted-foreground" role="status">Waiting for the first picture…</p>}
      <p className="m-0 text-[12.5px] text-muted-foreground" role="status">
        {screen?.resolution} · target {activeFps} fps{frame?.width && frame?.height ? ` · ${frame.width}×${frame.height}` : ""}
        {typeof frame?.fps === "number" ? ` · receiving ${frame.fps.toFixed(1)} fps` : ""}
        {typeof frame?.shown === "number" ? ` · showing ${frame.shown.toFixed(1)} fps` : ""}. Protected content stays black; nothing is recorded.
      </p>
    </div>}
    {live && screen?.message && <p role="status" className="m-0 text-center text-[12.5px] text-muted-foreground">{screen.message}</p>}
    {notice && <p role="alert" className="inline-error m-0 text-[12.5px]">{notice}</p>}
    {!code && !live && !waiting && screen?.message && <p role="status" className="m-0 text-[12.5px] text-muted-foreground">{screen.message}</p>}
    {waiting && screen?.message && <p className="m-0 text-center text-[12.5px] text-muted-foreground">{screen.message}</p>}
  </div>;
}
