// SPDX-License-Identifier: AGPL-3.0-or-later
// Saiph's visual language: a field of strings that ripple like plucked guitar
// strings. The background, loaders, progress and the brand mark all share it.
import { useEffect, useId, useRef } from "react";

export function reducedMotion() {
  return typeof window === "undefined" || typeof window.matchMedia !== "function" || window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

const STRINGS = 30;

type Rgb = [number, number, number];
/** A colour token resolved to rgb, so canvas strokes follow the design tokens. */
function tokenRgb(name: string, fallback: Rgb): Rgb {
  if (typeof document === "undefined" || !document.body || typeof getComputedStyle !== "function") return fallback;
  const probe = document.createElement("i");
  probe.style.color = `var(${name})`;
  probe.style.display = "none";
  document.body.appendChild(probe);
  const match = getComputedStyle(probe).color.match(/\d+(\.\d+)?/g);
  probe.remove();
  return match && match.length >= 3 ? [Number(match[0]), Number(match[1]), Number(match[2])] : fallback;
}
function alpha([r, g, b]: Rgb, a: number) { return `rgba(${r}, ${g}, ${b}, ${a})`; }

/**
 * Full-window string field: a still picture, drawn once and redrawn only when
 * the window is resized or the theme changes. Purely decorative: it never moves,
 * and nothing on the page (pointer, buttons, progress) makes it move. A
 * still background next to a moving one reads as parts of the window twitching.
 */
export function WaveField() {
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const element = canvas.current;
    const context = element?.getContext?.("2d");
    if (!element || !context) return;
    let layout = 0;

    function draw() {
      // Thin lines gain little above 1.5x and cost twice the pixels at 2x.
      const ratio = Math.min(window.devicePixelRatio || 1, 1.5);
      const width = window.innerWidth, height = window.innerHeight;
      element!.width = Math.round(width * ratio); element!.height = Math.round(height * ratio);
      context!.setTransform(ratio, 0, 0, ratio, 0, 0);
      context!.clearRect(0, 0, width, height);
      const one = tokenRgb("--wave-1", [34, 211, 238]), two = tokenRgb("--wave-2", [103, 232, 249]), three = tokenRgb("--wave-3", [167, 139, 250]);
      const gap = height / (STRINGS + 1);
      const step = Math.max(5, width / 220);
      for (let i = 1; i <= STRINGS; i++) {
        const base = i * gap;
        const depth = i / (STRINGS + 1);
        // Strings fade towards the top and bottom edges.
        const level = 0.07 + 0.26 * Math.sin(Math.PI * depth) ** 2;
        const gradient = context!.createLinearGradient(0, 0, width, 0);
        gradient.addColorStop(0, alpha(one, level * 0.35));
        gradient.addColorStop(0.45, alpha(two, level));
        gradient.addColorStop(1, alpha(three, level * 0.55));
        context!.strokeStyle = gradient;
        context!.lineWidth = 1;
        context!.beginPath();
        for (let x = -step; x <= width + step; x += step) {
          const u = x / width;
          // Contour: wide swells that make the strings look like terrain lines,
          // with a fine ripple along every string.
          const y = base + Math.sin(u * 2.6 + depth * 4.1) * gap * 0.9 + Math.sin(u * 6.3 - depth * 2.2) * gap * 0.25
            + Math.sin(u * 22 + i * 0.7) * 1.2;
          if (x === -step) context!.moveTo(x, y); else context!.lineTo(x, y);
        }
        context!.stroke();
      }
    }
    // Resizing clears the canvas, so it is redrawn in the same frame; the many
    // events of a dragged window edge coalesce into one redraw per frame.
    function relayout() {
      if (!layout) layout = requestAnimationFrame(() => { layout = 0; draw(); });
    }

    draw();
    window.addEventListener("resize", relayout);
    // Colours come from tokens, which follow the system scheme and the root element.
    const scheme = typeof window.matchMedia === "function" ? window.matchMedia("(prefers-color-scheme: dark)") : null;
    scheme?.addEventListener?.("change", relayout);
    const theme = typeof MutationObserver === "function" ? new MutationObserver(relayout) : null;
    theme?.observe(document.documentElement, { attributes: true, attributeFilter: ["class", "style", "data-theme"] });
    return () => {
      if (layout) cancelAnimationFrame(layout);
      window.removeEventListener("resize", relayout);
      scheme?.removeEventListener?.("change", relayout);
      theme?.disconnect();
    };
  }, []);
  return <div className="wave-field" aria-hidden="true"><canvas ref={canvas} /></div>;
}

// The selected-tab wave moves 1 px at this rate, forever. One timer moves every
// underline at once, and no CSS animation runs, so the window presents exactly
// these frames for it (each costs about 1 % of a core in Qt WebEngine).
export const WAVE_HZ = 8;
const WAVE_PERIOD = 12;
let waveTicker: { users: number; stop: () => void } | null = null;

/** Starts the shared underline timer; the returned function releases it. */
export function startWaveTicker() {
  if (typeof window === "undefined" || reducedMotion()) return () => {};
  if (!waveTicker) {
    const lines = document.getElementsByClassName("wave-underline") as HTMLCollectionOf<HTMLElement>;
    let shift = 0, timer = 0;
    const step = () => {
      shift = (shift + 1) % WAVE_PERIOD;
      for (const line of Array.from(lines)) line.style.setProperty("--wave-shift", `-${shift}px`);
    };
    // A hidden window shows nothing, so it moves nothing.
    const run = () => {
      window.clearInterval(timer);
      timer = document.visibilityState === "hidden" ? 0 : window.setInterval(step, 1000 / WAVE_HZ);
    };
    run();
    document.addEventListener("visibilitychange", run);
    waveTicker = { users: 0, stop: () => { window.clearInterval(timer); document.removeEventListener("visibilitychange", run); } };
  }
  const ticker = waveTicker;
  ticker.users += 1;
  return () => {
    ticker.users -= 1;
    if (!ticker.users && waveTicker === ticker) { ticker.stop(); waveTicker = null; }
  };
}

// A string fixed at both ends, drawn at several moments of its vibration.
function stringFrames(length: number, amplitude: number, harmonic: number, mid: number, frames = 8) {
  const out: string[] = [];
  for (let f = 0; f <= frames; f++) {
    const swing = Math.cos((f / frames) * Math.PI * 2) * amplitude;
    let d = `M0 ${mid}`;
    for (let x = 4; x <= length; x += 4) d += ` L${x} ${(mid + Math.sin((x / length) * Math.PI * harmonic) * swing).toFixed(2)}`;
    out.push(d);
  }
  return out.join(";");
}

/**
 * Saiph's mark: three stars joined by a vibrating string. The middle star is
 * where the string is held, so it stays still while the halves ring.
 */
export function SaiphMark({ size = 32, animated = true }: { size?: number; animated?: boolean }) {
  const id = useId().replace(/:/g, "");
  const motion = animated && !reducedMotion();
  // Control points move perpendicular to the diagonal, in opposite directions.
  const pose = (a: number) => `M8 29Q${(14 + 0.55 * a).toFixed(2)} ${(24.5 + 0.83 * a).toFixed(2)} 20 20Q${(26 - 0.55 * a).toFixed(2)} ${(15.5 - 0.83 * a).toFixed(2)} 32 11`;
  const poses = [4.2, 0, -4.2, 0, 4.2].map(pose).join(";");
  const echo = [-2.6, 0, 2.6, 0, -2.6].map(pose).join(";");
  return <svg className="saiph-mark" width={size} height={size} viewBox="0 0 40 40" role="img" aria-label="Saiph">
    <defs>
      <linearGradient id={`${id}s`} x1="8" y1="29" x2="32" y2="11" gradientUnits="userSpaceOnUse">
        <stop offset="0" style={{ stopColor: "var(--wave-1)" }} /><stop offset=".5" style={{ stopColor: "var(--wave-star)" }} /><stop offset="1" style={{ stopColor: "var(--wave-3)" }} />
      </linearGradient>
      <radialGradient id={`${id}g`}><stop offset="0" style={{ stopColor: "var(--wave-2)", stopOpacity: 0.55 }} /><stop offset="1" style={{ stopColor: "var(--wave-2)", stopOpacity: 0 }} /></radialGradient>
    </defs>
    <circle cx="20" cy="20" r="11" fill={`url(#${id}g)`}>
      {motion && <animate attributeName="r" values="9;12.5;9" dur="3.2s" repeatCount="indefinite" />}
    </circle>
    <path d={pose(0)} fill="none" stroke={`url(#${id}s)`} strokeOpacity=".35" strokeWidth=".9">
      {motion && <animate attributeName="d" values={echo} dur="1.6s" repeatCount="indefinite" />}
    </path>
    <path d={pose(2.4)} fill="none" stroke={`url(#${id}s)`} strokeWidth="1.6" strokeLinecap="round">
      {motion && <animate attributeName="d" values={poses} dur="1.1s" repeatCount="indefinite" />}
    </path>
    <circle cx="8" cy="29" r="2.6" style={{ fill: "var(--wave-2)" }} />
    <circle cx="20" cy="20" r="3" style={{ fill: "var(--wave-star)" }} />
    <circle cx="32" cy="11" r="2.6" style={{ fill: "var(--wave-3)" }} />
  </svg>;
}

/** Indeterminate loader: one string ringing through its first harmonics. */
export function WaveLoader({ label, size = 120 }: { label?: string; size?: number }) {
  const id = useId().replace(/:/g, "");
  const motion = !reducedMotion();
  const harmonics = [1, 2, 3];
  return <span className="wave-loader" role={label ? "status" : undefined}>
    <svg width={size} height={size / 4} viewBox="0 0 120 30" aria-hidden="true">
      <defs><linearGradient id={`${id}l`} x1="0" x2="1"><stop offset="0" style={{ stopColor: "var(--wave-1)" }} /><stop offset=".55" style={{ stopColor: "var(--wave-2)" }} /><stop offset="1" style={{ stopColor: "var(--wave-3)" }} /></linearGradient></defs>
      {harmonics.map((h, n) => <path key={h} d={`M0 15 L120 15`} fill="none" stroke={`url(#${id}l)`} strokeWidth={n === 0 ? 1.8 : 1} strokeOpacity={n === 0 ? 1 : 0.45} strokeLinecap="round">
        {motion && <animate attributeName="d" values={stringFrames(120, 11 / h, h, 15)} dur={`${0.9 + n * 0.35}s`} repeatCount="indefinite" />}
      </path>)}
      <circle cx="0.8" cy="15" r="1.6" style={{ fill: "var(--wave-2)" }} /><circle cx="119.2" cy="15" r="1.6" style={{ fill: "var(--wave-3)" }} />
    </svg>
    {label && <span>{label}</span>}
  </span>;
}

/** Step progress drawn as a string between stars. The finished stretch carries a travelling wave. */
export function WaveProgress({ steps, current, done = [] }: { steps: string[]; current: number; done?: number[] }) {
  const id = useId().replace(/:/g, "");
  const width = 600, period = 40;
  const span = steps.length > 1 ? width / (steps.length - 1) : width;
  const reached = Math.max(0, Math.min(steps.length - 1, current)) * span;
  let wave = "M0 12";
  for (let x = 0; x <= width + period; x += 2) wave += ` L${x} ${(12 + Math.sin((x / period) * Math.PI * 2) * 3).toFixed(2)}`;
  return <div className="wave-progress">
    <svg viewBox={`0 0 ${width} 24`} preserveAspectRatio="none" aria-hidden="true" className="wave-progress-line"
      style={{ left: `${50 / steps.length}%`, width: `${100 - 100 / steps.length}%` }}>
      <defs>
        <linearGradient id={`${id}p`} x1="0" x2={width} gradientUnits="userSpaceOnUse"><stop offset="0" style={{ stopColor: "var(--wave-1)" }} /><stop offset="1" style={{ stopColor: "var(--wave-3)" }} /></linearGradient>
        <clipPath id={`${id}c`}><rect x="0" y="0" height="24" width={reached} style={{ width: reached }} className="wave-progress-reach" /></clipPath>
      </defs>
      <line x1="0" y1="12" x2={width} y2="12" className="wave-progress-rest" />
      <g clipPath={`url(#${id}c)`}><path d={wave} className="wave-progress-run" stroke={`url(#${id}p)`} /></g>
    </svg>
    <ol aria-label="Setup steps">{steps.map((name, index) =>
      <li key={name} aria-current={index === current ? "step" : undefined} className={index < current || done.includes(index) ? "done" : ""}>
        <span className="wave-node" aria-hidden="true" /><span className="wave-step-name">{name}</span></li>)}</ol>
  </div>;
}
