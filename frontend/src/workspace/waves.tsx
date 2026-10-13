// SPDX-License-Identifier: AGPL-3.0-or-later
// Saiph's visual language: a field of strings that ripple like plucked guitar
// strings. The background, loaders, progress and the brand mark all share it.
import { useEffect, useId, useRef } from "react";

type Pluck = { x: number; y: number; strength: number; born: number };
type Gather = { id: number; x: number; y: number; radius: number };

// One shared field per window. Components pluck it or gather its strings to a
// point while they work, without needing a reference to the canvas.
const field = { plucks: [] as Pluck[], gathers: [] as Gather[], next: 1 };

function now() { return typeof performance === "undefined" ? Date.now() : performance.now(); }

export function reducedMotion() {
  return typeof window === "undefined" || typeof window.matchMedia !== "function" || window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** Sends a ripple through the strings near a window point (CSS pixels). */
export function pluck(x: number, y: number, strength = 1) {
  field.plucks.push({ x, y, strength, born: now() });
  if (field.plucks.length > 24) field.plucks.shift();
}

/**
 * Curls the strings around a ball at a point, ringing where they touch it,
 * until released. This is Saiph's "working" state.
 */
export function gather(x: number, y: number, radius = 90) {
  const id = field.next++;
  field.gathers.push({ id, x, y, radius });
  return () => { field.gathers = field.gathers.filter((g) => g.id !== id); };
}

/** Gathers the strings around an element while `active` is true. */
export function useGather(ref: React.RefObject<Element | null>, active: boolean) {
  useEffect(() => {
    const element = ref.current;
    if (!active || !element || typeof element.getBoundingClientRect !== "function") return;
    const box = element.getBoundingClientRect();
    if (!box.width && !box.height) return;
    const x = box.left + box.width / 2, y = box.top + box.height / 2;
    const release = gather(x, y, Math.min(70, Math.max(box.width, box.height) / 2 + 18));
    return () => { release(); pluck(x, y, 0.8); };
  }, [ref, active]);
}

const STRINGS = 30;

// Ideal flow around a cylinder: the height at `dx` of the streamline that sits
// `far` above the centre far away. Strings part smoothly around the ball.
function streamline(dx: number, far: number, radius: number) {
  const x2 = dx * dx, r2 = radius * radius;
  let y = far + radius;
  for (let n = 0; n < 8; n++) {
    const f = y * y * y - far * y * y + (x2 - r2) * y - far * x2;
    const slope = 3 * y * y - 2 * far * y + x2 - r2;
    if (!slope) break;
    y -= f / slope;
  }
  return y;
}

function ease(value: number) { return value < 0 ? 0 : value > 1 ? 1 : value * value * (3 - 2 * value); }

/** Full-window animated string field. Purely decorative. */
export function WaveField() {
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const element = canvas.current;
    const context = element?.getContext?.("2d");
    if (!element || !context) return;
    const still = reducedMotion();
    let width = 0, height = 0, frame = 0, visible = true, pointerAt = 0, previous = 0;
    const start = now();
    const knots = new Map<number, { x: number; y: number; radius: number; level: number }>();

    function resize() {
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      width = window.innerWidth; height = window.innerHeight;
      element!.width = Math.round(width * ratio); element!.height = Math.round(height * ratio);
      context!.setTransform(ratio, 0, 0, ratio, 0, 0);
    }

    function draw(time: number) {
      const t = (time - start) / 1000;
      // Ramps run on elapsed time, so slow or throttled frames look the same.
      const elapsed = previous ? Math.min(0.1, (time - previous) / 1000) : 0;
      previous = time;
      context!.clearRect(0, 0, width, height);
      const gap = height / (STRINGS + 1);
      const step = Math.max(4, width / 260);
      const balls = [...knots.values()].map((k) => ({ ...k, level: ease(k.level) }));
      // A faint glow marks each ball the strings are wrapped around.
      for (const b of balls) {
        const glow = context!.createRadialGradient(b.x, b.y, 0, b.x, b.y, b.radius * 1.6);
        glow.addColorStop(0, `rgba(103, 232, 249, ${0.1 * b.level})`);
        glow.addColorStop(0.6, `rgba(96, 165, 250, ${0.05 * b.level})`);
        glow.addColorStop(1, "rgba(96, 165, 250, 0)");
        context!.fillStyle = glow;
        context!.fillRect(b.x - b.radius * 2, b.y - b.radius * 2, b.radius * 4, b.radius * 4);
      }
      // Held gathers ramp in; released ones relax back instead of snapping.
      const active = new Set(field.gathers.map((g) => g.id));
      for (const g of field.gathers) {
        const knot = knots.get(g.id) || { ...g, level: 0 };
        knots.set(g.id, { ...g, level: Math.min(1, knot.level + elapsed * 1.8) });
      }
      for (const [id, knot] of knots) if (!active.has(id)) {
        knot.level -= elapsed * 1.1;
        if (knot.level <= 0) knots.delete(id);
      }
      field.plucks = field.plucks.filter((p) => time - p.born < 4000);

      for (let i = 1; i <= STRINGS; i++) {
        const base = i * gap;
        const depth = i / (STRINGS + 1);
        // Strings fade towards the top and bottom edges.
        const alpha = 0.07 + 0.26 * Math.sin(Math.PI * depth) ** 2;
        const gradient = context!.createLinearGradient(0, 0, width, 0);
        gradient.addColorStop(0, `rgba(34, 211, 238, ${alpha * 0.35})`);
        gradient.addColorStop(0.45, `rgba(103, 232, 249, ${alpha})`);
        gradient.addColorStop(1, `rgba(167, 139, 250, ${alpha * 0.55})`);
        context!.strokeStyle = gradient;
        context!.lineWidth = 1;
        context!.beginPath();
        for (let x = -step; x <= width + step; x += step) {
          const u = x / width;
          // Contour: slow, wide swells that make the strings look like terrain lines.
          let y = base + Math.sin(u * 2.6 + depth * 4.1 + t * 0.12) * gap * 0.9 + Math.sin(u * 6.3 - depth * 2.2 - t * 0.21) * gap * 0.25;
          // Hum: a fine, slow ripple along every string.
          y += Math.sin(u * 22 - t * 0.9 + i * 0.7) * 1.2;
          for (const p of field.plucks) {
            const age = (time - p.born) / 1000;
            const dx = x - p.x, dy = base - p.y;
            const reach = Math.exp(-(dy * dy) / (2 * (gap * 3.2) ** 2));
            const front = Math.abs(dx) - age * 520;
            const envelope = Math.exp(-(front * front) / 9000) * Math.exp(-age * 1.3);
            y += Math.sin(dx * 0.045 - age * 18) * 16 * p.strength * reach * envelope;
          }
          for (const b of balls) {
            const offset = y - b.y;
            if (Math.abs(offset) > b.radius * 7) continue;
            const dx = x - b.x, side = offset === 0 ? (i % 2 ? 1 : -1) : Math.sign(offset);
            const wrapped = b.y + streamline(dx, Math.abs(offset) || 0.5, b.radius) * side;
            // Fade the influence out smoothly so distant strings never kink.
            const reach = Math.exp(-((Math.max(0, Math.abs(offset) - b.radius * 1.5) / (b.radius * 1.6)) ** 2));
            y += (wrapped - y) * b.level * reach;
            // Where the strings hug the ball they ring like a struck string.
            const touch = Math.hypot(dx, y - b.y) - b.radius;
            y += Math.sin(t * 17 + i * 1.9 + dx * 0.06) * 3.2 * Math.exp(-(touch * touch) / 260) * b.level;
          }
          if (x === -step) context!.moveTo(x, y); else context!.lineTo(x, y);
        }
        context!.stroke();
      }
    }

    function loop(time: number) {
      if (visible) draw(time);
      frame = requestAnimationFrame(loop);
    }
    function onVisibility() { visible = document.visibilityState !== "hidden"; }
    function onPointer(event: PointerEvent) {
      // Moving across the window brushes the strings softly.
      const time = now();
      if (time - pointerAt < 140) return;
      pointerAt = time;
      pluck(event.clientX, event.clientY, 0.18);
    }
    function onDown(event: PointerEvent) { pluck(event.clientX, event.clientY, 0.55); }

    resize();
    window.addEventListener("resize", resize);
    if (still) { draw(start); return () => window.removeEventListener("resize", resize); }
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("pointermove", onPointer, { passive: true });
    window.addEventListener("pointerdown", onDown, { passive: true });
    frame = requestAnimationFrame(loop);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", resize);
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("pointermove", onPointer);
      window.removeEventListener("pointerdown", onDown);
    };
  }, []);
  return <div className="wave-field" aria-hidden="true"><canvas ref={canvas} /></div>;
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
        <stop offset="0" stopColor="#22d3ee" /><stop offset=".5" stopColor="#e7f6ff" /><stop offset="1" stopColor="#a78bfa" />
      </linearGradient>
      <radialGradient id={`${id}g`}><stop offset="0" stopColor="#67e8f9" stopOpacity=".55" /><stop offset="1" stopColor="#67e8f9" stopOpacity="0" /></radialGradient>
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
    <circle cx="8" cy="29" r="2.6" fill="#67e8f9" />
    <circle cx="20" cy="20" r="3" fill="#f2f8ff" />
    <circle cx="32" cy="11" r="2.6" fill="#b9a6fb" />
  </svg>;
}

/** Indeterminate loader: one string ringing through its first harmonics. */
export function WaveLoader({ label, size = 120 }: { label?: string; size?: number }) {
  const id = useId().replace(/:/g, "");
  const motion = !reducedMotion();
  const harmonics = [1, 2, 3];
  return <span className="wave-loader" role={label ? "status" : undefined}>
    <svg width={size} height={size / 4} viewBox="0 0 120 30" aria-hidden="true">
      <defs><linearGradient id={`${id}l`} x1="0" x2="1"><stop offset="0" stopColor="#22d3ee" /><stop offset=".55" stopColor="#67e8f9" /><stop offset="1" stopColor="#a78bfa" /></linearGradient></defs>
      {harmonics.map((h, n) => <path key={h} d={`M0 15 L120 15`} fill="none" stroke={`url(#${id}l)`} strokeWidth={n === 0 ? 1.8 : 1} strokeOpacity={n === 0 ? 1 : 0.45} strokeLinecap="round">
        {motion && <animate attributeName="d" values={stringFrames(120, 11 / h, h, 15)} dur={`${0.9 + n * 0.35}s`} repeatCount="indefinite" />}
      </path>)}
      <circle cx="0.8" cy="15" r="1.6" fill="#67e8f9" /><circle cx="119.2" cy="15" r="1.6" fill="#b9a6fb" />
    </svg>
    {label && <span>{label}</span>}
  </span>;
}

/**
 * Step progress drawn as a string between stars. The finished stretch carries
 * a travelling wave; each step change plucks it.
 */
export function WaveProgress({ steps, current, done = [] }: { steps: string[]; current: number; done?: number[] }) {
  const id = useId().replace(/:/g, "");
  const line = useRef<SVGSVGElement>(null);
  const width = 600, period = 40;
  const span = steps.length > 1 ? width / (steps.length - 1) : width;
  const reached = Math.max(0, Math.min(steps.length - 1, current)) * span;
  let wave = "M0 12";
  for (let x = 0; x <= width + period; x += 2) wave += ` L${x} ${(12 + Math.sin((x / period) * Math.PI * 2) * 3).toFixed(2)}`;
  useEffect(() => {
    const element = line.current;
    if (!element || typeof element.getBoundingClientRect !== "function") return;
    const box = element.getBoundingClientRect();
    if (box.width) pluck(box.left + (reached / width) * box.width, box.top + box.height / 2, 1);
  }, [reached]);
  return <div className="wave-progress">
    <svg ref={line} viewBox={`0 0 ${width} 24`} preserveAspectRatio="none" aria-hidden="true" className="wave-progress-line"
      style={{ left: `${50 / steps.length}%`, width: `${100 - 100 / steps.length}%` }}>
      <defs>
        <linearGradient id={`${id}p`} x1="0" x2={width} gradientUnits="userSpaceOnUse"><stop offset="0" stopColor="#22d3ee" /><stop offset="1" stopColor="#a78bfa" /></linearGradient>
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
