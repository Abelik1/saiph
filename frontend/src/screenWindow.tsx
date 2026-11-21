// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { ArrowLeft, Circle, Square, RotateCw, X } from "lucide-react";
import { desktopClient } from "./workspace/client";
import { followFrames } from "./workspace/frameFeed";
import { framePoint, gesture, typed, type ScreenEvent } from "./workspace/PhoneScreen";
import type { Client } from "./workspace/types";
import "./index.css";

function ScreenWindow() {
  const [client, setClient] = useState<Client>();
  const [control, setControl] = useState(false), [rotation, setRotation] = useState(0), [notice, setNotice] = useState("");
  const image = useRef<HTMLImageElement>(null), area = useRef<HTMLDivElement>(null);
  const press = useRef<{ x: number; y: number; at: number } | null>(null);
  const wheelAt = useRef(0), composing = useRef(false);
  const [size, setSize] = useState({ width: 360, height: 640 });
  useEffect(() => { void desktopClient().then(setClient, error => setNotice(String(error))); }, []);
  useEffect(() => {
    if (!client) return;
    let active = true;
    const refresh = () => void client.call<{ input: boolean }>("screen.status").then(value => { if (active) setControl(value.input); }, () => {});
    refresh();
    const unsubscribe = client.subscribe(refresh);
    const frames = followFrames(client, "screen", (_info, _picture, url) => { if (image.current) image.current.src = url; });
    return () => { active = false; unsubscribe(); frames?.(); };
  }, [client]);
  useEffect(() => {
    const observer = new ResizeObserver(entries => { const rect = entries[0]?.contentRect; if (rect) setSize({ width: rect.width, height: rect.height }); });
    if (area.current) observer.observe(area.current);
    return () => observer.disconnect();
  }, []);
  const send = (event: ScreenEvent) => {
    if (!control) return;
    void client?.call("screen.input", { event }).then(() => setNotice(""), error => setNotice(error.message));
  };
  const point = (x: number, y: number) => {
    const element = image.current;
    if (!element) return null;
    const turned = rotation % 180 !== 0;
    const result = framePoint(element.getBoundingClientRect(),
      { width: turned ? element.naturalHeight : element.naturalWidth, height: turned ? element.naturalWidth : element.naturalHeight }, x, y);
    if (!result) return null;
    const { x: u, y: v } = result;
    return rotation === 90 ? { x: v, y: 10000 - u } : rotation === 180 ? { x: 10000 - u, y: 10000 - v }
      : rotation === 270 ? { x: 10000 - v, y: u } : result;
  };
  return <div style={{ height: "100vh", display: "flex", flexDirection: "column", background: "var(--background)", border: "2px solid var(--live-ring)" }}>
    <header style={{ display: "flex", gap: 8, padding: 8, alignItems: "center", background: "var(--chrome)" }}>
      <span style={{ color: "var(--live-ring)", fontWeight: 600 }}>● Live</span>
      <span style={{ flex: 1 }}>{notice || (control ? "Control on" : "View only")}</span>
      {([["Back", ArrowLeft, "back"], ["Home", Circle, "home"], ["Recents", Square, "recents"]] as const).map(([label, Icon, key]) =>
        <button key={key} aria-label={label} disabled={!control} onClick={() => send({ t: "key", key })}><Icon size={16} /></button>)}
      <button aria-label="Rotate view" onClick={() => setRotation(value => (value + 90) % 360)}><RotateCw size={16} /></button>
      <button aria-label="Stop sharing" onClick={() => void client?.call("screen.stop")}><X size={16} /></button>
    </header>
    <div ref={area} tabIndex={0} role="application" aria-label="Phone screen" style={{ flex: 1, position: "relative", overflow: "hidden", outline: "none" }}
      onPointerDown={event => { const p = point(event.clientX, event.clientY); if (p) { event.currentTarget.setPointerCapture(event.pointerId); press.current = { ...p, at: performance.now() }; event.currentTarget.focus(); } }}
      onPointerUp={event => { const end = point(event.clientX, event.clientY), start = press.current; press.current = null; if (start && end) send(gesture(start, { ...end, at: performance.now() })); }}
      onPointerCancel={() => { press.current = null; }}
      onWheel={event => { const now = performance.now(); if (now - wheelAt.current < 200 || !event.deltaY) return; const p = point(event.clientX, event.clientY); if (p) { wheelAt.current = now; send({ t: "swipe", ...p, x2: p.x, y2: Math.max(0, Math.min(10000, p.y + (event.deltaY > 0 ? 2500 : -2500))), ms: 250 }); } }}
      onCompositionStart={() => { composing.current = true; }}
      onCompositionEnd={event => { composing.current = false; if (event.data) send({ t: "text", text: typed(event.data) }); }}
      onKeyDown={event => { if (composing.current || event.nativeEvent.isComposing || event.ctrlKey || event.metaKey || event.altKey) return; if (event.key === "Backspace" || event.key === "Enter" || event.key === "Escape") { event.preventDefault(); send({ t: "key", key: event.key === "Backspace" ? "backspace" : event.key === "Enter" ? "enter" : "back" }); } else if (event.key.length === 1) { event.preventDefault(); send({ t: "text", text: typed(event.key) }); } }}
      onPaste={event => { event.preventDefault(); send({ t: "text", text: typed(event.clipboardData.getData("text/plain")) }); }}>
      <img ref={image} alt="Live phone screen" draggable={false} style={{ position: "absolute", left: "50%", top: "50%", objectFit: "contain", width: rotation % 180 ? size.height : size.width, height: rotation % 180 ? size.width : size.height, transform: `translate(-50%, -50%) rotate(${rotation}deg)` }} />
    </div>
  </div>;
}
createRoot(document.getElementById("root")!).render(<ScreenWindow />);
