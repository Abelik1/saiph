// Shared motion for the renderer comparison. blender/motion.py mirrors every
// function here line for line, so both renderers place the same thing at the
// same moment. Positions are in three.js axes (y up).

export const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
export const smooth = (x) => { x = clamp(x); return x * x * x * (x * (x * 6 - 15) + 10); };
const lerp = (a, b, u) => a + (b - a) * u;
const add = (a, b) => a.map((v, i) => v + b[i]);
const sub = (a, b) => a.map((v, i) => v - b[i]);
const mul = (a, k) => a.map((v) => v * k);
const norm = (a) => { const l = Math.hypot(...a) || 1; return mul(a, 1 / l); };
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];

function catmull(p0, p1, p2, p3, u) {
  const u2 = u * u, u3 = u2 * u;
  return p1.map((_, i) => 0.5 * (2 * p1[i] + (-p0[i] + p2[i]) * u + (2 * p0[i] - 5 * p1[i] + 4 * p2[i] - p3[i]) * u2
    + (-p0[i] + 3 * p1[i] - 3 * p2[i] + p3[i]) * u3));
}

/** Camera position, look target and focus distance at time t. */
export function cameraAt(scene, t) {
  const keys = scene.camera.keys;
  let i = 0;
  while (i < keys.length - 2 && t > keys[i + 1].t) i++;
  const k1 = keys[i], k2 = keys[i + 1], k0 = keys[Math.max(0, i - 1)], k3 = keys[Math.min(keys.length - 1, i + 2)];
  const u = clamp((t - k1.t) / (k2.t - k1.t));
  const pick = (name) => catmull(k0[name], k1[name], k2[name], k3[name], u);
  const focus = catmull([k0.focus], [k1.focus], [k2.focus], [k3.focus], u)[0];
  return { pos: pick("pos"), look: pick("look"), focus };
}

/** Camera basis (x, y, z columns) looking from pos to look with y up. */
export function lookBasis(pos, look) {
  const z = norm(sub(pos, look));
  const x = norm(cross([0, 1, 0], z));
  return { x, y: cross(z, x), z };
}

/** Floating motion added to each device. */
export function phonePose(scene, t) {
  const p = scene.phone;
  return { position: add(p.position, [0, 0.04 * Math.sin(1.15 * t), 0]),
    rotation: add(p.rotation, [0.015 * Math.sin(0.7 * t + 2), 0, 0.02 * Math.sin(0.9 * t + 1)]) };
}
export function laptopPose(scene, t) {
  const l = scene.laptop;
  return { position: add(l.position, [0, 0.025 * Math.sin(0.85 * t + 2), 0]), rotation: l.rotation.slice() };
}

/** Lid tilt back from upright, in radians (negative x rotation). */
export const lidTilt = (scene) => -(scene.laptop.lidOpen - Math.PI / 2);

/** Screen centre in the lid's hinge frame; the lid's back face sits on the hinge plane. */
export function screenLocal(scene) {
  const l = scene.laptop;
  return [0, l.lid[1] / 2 + 0.04, l.lid[2] + 0.002];
}

/** Hinge-frame point at the centre of the arriving photo's tile. */
export function tileLocal(scene) {
  const l = scene.laptop, [sw, sh] = l.screenSize, c = screenLocal(scene);
  return [(l.tile.u - 0.5) * sw, c[1] + (0.5 - l.tile.v) * sh, c[2] + 0.006];
}

/** Phone-frame point just above the top edge, where the string and photo leave. */
export const phoneLaunchLocal = (scene) => [0, scene.phone.size[1] / 2 + 0.04, 0.02];

/** Hero string: launch progress, vibration and visibility for time t. */
export function heroState(scene, t) {
  const h = scene.hero;
  const since = t - h.pluck;
  const travel = smooth((t - h.launch) / (h.arrive - h.launch));
  const vibration = since < 0 ? 0 : h.amplitude * Math.exp(-h.decay * since);
  const cardOpacity = clamp((t - h.launch + 0.15) / 0.15) * (1 - clamp((t - h.arrive - 0.05) / 0.3));
  const arrived = smooth((t - h.arrive + 0.05) / 0.4);
  return { since, travel, vibration, cardOpacity, arrived };
}

/** Point s (0..1) on the hero string between start p0 and end p1. */
export function heroPoint(scene, t, p0, p1, s) {
  const h = scene.hero, st = heroState(scene, t);
  const mid = add(mul(add(p0, p1), 0.5), [0, h.lift, 0]);
  const a = (1 - s) * (1 - s), b = 2 * s * (1 - s), c = s * s;
  const base = add(add(mul(p0, a), mul(mid, b)), mul(p1, c));
  const idle = 0.012 * Math.sin(Math.PI * s) * Math.sin(2.1 * t);
  const ring = st.since < 0 ? 0 : st.vibration * (Math.sin(Math.PI * s) * Math.sin(2 * Math.PI * 3.2 * st.since)
    + 0.4 * Math.sin(2 * Math.PI * s) * Math.sin(2 * Math.PI * 5.1 * st.since));
  return add(base, [0, idle + ring, 0]);
}

/** Ripple height and strength at a floor point, centred under the phone. */
function ripple(scene, t, x, z) {
  const r = scene.ripple, since = t - r.start;
  if (since < 0) return 0;
  const d = Math.hypot(x - scene.phone.position[0], z - scene.phone.position[2]);
  const front = r.speed * since;
  return Math.exp(-(((d - front) / r.width) ** 2)) * Math.exp(-0.35 * since);
}

/** Floor string i: its points and brightness level at time t. */
export function floorString(scene, t, i) {
  const s = scene.strings, n = s.count, depth = (i + 1) / (n + 1);
  const z = lerp(s.zRange[0], s.zRange[1], depth);
  const points = [];
  let peak = 0;
  for (let k = 0; k <= s.segments; k++) {
    const u = k / s.segments, x = lerp(s.xRange[0], s.xRange[1], u), w = u * 1.6;
    const bump = ripple(scene, t, x, z);
    peak = Math.max(peak, bump);
    const y = s.baseY + s.swell * (0.9 * Math.sin(w * 2.6 + depth * 4.1 + s.drift * t) + 0.25 * Math.sin(w * 6.3 - depth * 2.2 - s.drift * 0.6 * t))
      + 0.012 * Math.sin(u * 22 + i * 0.7 + t) + scene.ripple.height * bump;
    points.push([x, y, z]);
  }
  const level = (0.07 + 0.26 * Math.sin(Math.PI * depth) ** 2) * (1 + 1.6 * peak);
  return { points, level };
}

/** Horizontal field of view kept for every format; vertical follows the aspect. */
export const verticalFov = (scene, aspect) => 2 * Math.atan(Math.tan(scene.camera.hfov / 2) / aspect);
