# Python mirror of ../motion.js. Keep the two in step: both renderers must place
# the same thing at the same moment. Positions are in three.js axes (y up).
import math


def clamp(x, a=0.0, b=1.0):
    return min(b, max(a, x))


def smooth(x):
    x = clamp(x)
    return x * x * x * (x * (x * 6 - 15) + 10)


def lerp(a, b, u):
    return a + (b - a) * u


def add(a, b):
    return [x + y for x, y in zip(a, b)]


def sub(a, b):
    return [x - y for x, y in zip(a, b)]


def mul(a, k):
    return [x * k for x in a]


def norm(a):
    length = math.sqrt(sum(x * x for x in a)) or 1.0
    return mul(a, 1 / length)


def cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def catmull(p0, p1, p2, p3, u):
    u2, u3 = u * u, u * u * u
    return [0.5 * (2 * p1[i] + (-p0[i] + p2[i]) * u + (2 * p0[i] - 5 * p1[i] + 4 * p2[i] - p3[i]) * u2
                   + (-p0[i] + 3 * p1[i] - 3 * p2[i] + p3[i]) * u3) for i in range(len(p1))]


def camera_at(scene, t):
    keys = scene["camera"]["keys"]
    i = 0
    while i < len(keys) - 2 and t > keys[i + 1]["t"]:
        i += 1
    k1, k2 = keys[i], keys[i + 1]
    k0, k3 = keys[max(0, i - 1)], keys[min(len(keys) - 1, i + 2)]
    u = clamp((t - k1["t"]) / (k2["t"] - k1["t"]))
    pick = lambda name: catmull(k0[name], k1[name], k2[name], k3[name], u)
    focus = catmull([k0["focus"]], [k1["focus"]], [k2["focus"]], [k3["focus"]], u)[0]
    return {"pos": pick("pos"), "look": pick("look"), "focus": focus}


def look_basis(pos, look):
    z = norm(sub(pos, look))
    x = norm(cross([0, 1, 0], z))
    return {"x": x, "y": cross(z, x), "z": z}


def phone_pose(scene, t):
    p = scene["phone"]
    return {"position": add(p["position"], [0, 0.04 * math.sin(1.15 * t), 0]),
            "rotation": add(p["rotation"], [0.015 * math.sin(0.7 * t + 2), 0, 0.02 * math.sin(0.9 * t + 1)])}


def laptop_pose(scene, t):
    l = scene["laptop"]
    return {"position": add(l["position"], [0, 0.025 * math.sin(0.85 * t + 2), 0]), "rotation": list(l["rotation"])}


def lid_tilt(scene):
    return -(scene["laptop"]["lidOpen"] - math.pi / 2)


def screen_local(scene):
    l = scene["laptop"]
    return [0, l["lid"][1] / 2 + 0.04, l["lid"][2] + 0.002]


def tile_local(scene):
    l = scene["laptop"]
    sw, sh = l["screenSize"]
    c = screen_local(scene)
    return [(l["tile"]["u"] - 0.5) * sw, c[1] + (0.5 - l["tile"]["v"]) * sh, c[2] + 0.006]


def phone_launch_local(scene):
    return [0, scene["phone"]["size"][1] / 2 + 0.04, 0.02]


def hero_state(scene, t):
    h = scene["hero"]
    since = t - h["pluck"]
    travel = smooth((t - h["launch"]) / (h["arrive"] - h["launch"]))
    vibration = 0 if since < 0 else h["amplitude"] * math.exp(-h["decay"] * since)
    card_opacity = clamp((t - h["launch"] + 0.15) / 0.15) * (1 - clamp((t - h["arrive"] - 0.05) / 0.3))
    arrived = smooth((t - h["arrive"] + 0.05) / 0.4)
    return {"since": since, "travel": travel, "vibration": vibration, "cardOpacity": card_opacity, "arrived": arrived}


def hero_point(scene, t, p0, p1, s):
    h, st = scene["hero"], hero_state(scene, t)
    mid = add(mul(add(p0, p1), 0.5), [0, h["lift"], 0])
    a, b, c = (1 - s) * (1 - s), 2 * s * (1 - s), s * s
    base = add(add(mul(p0, a), mul(mid, b)), mul(p1, c))
    idle = 0.012 * math.sin(math.pi * s) * math.sin(2.1 * t)
    ring = 0 if st["since"] < 0 else st["vibration"] * (
        math.sin(math.pi * s) * math.sin(2 * math.pi * 3.2 * st["since"])
        + 0.4 * math.sin(2 * math.pi * s) * math.sin(2 * math.pi * 5.1 * st["since"]))
    return add(base, [0, idle + ring, 0])


def ripple(scene, t, x, z):
    r = scene["ripple"]
    since = t - r["start"]
    if since < 0:
        return 0
    d = math.hypot(x - scene["phone"]["position"][0], z - scene["phone"]["position"][2])
    front = r["speed"] * since
    return math.exp(-(((d - front) / r["width"]) ** 2)) * math.exp(-0.35 * since)


def floor_string(scene, t, i):
    s = scene["strings"]
    n = s["count"]
    depth = (i + 1) / (n + 1)
    z = lerp(s["zRange"][0], s["zRange"][1], depth)
    points, peak = [], 0.0
    for k in range(s["segments"] + 1):
        u = k / s["segments"]
        x = lerp(s["xRange"][0], s["xRange"][1], u)
        w = u * 1.6
        bump = ripple(scene, t, x, z)
        peak = max(peak, bump)
        y = (s["baseY"] + s["swell"] * (0.9 * math.sin(w * 2.6 + depth * 4.1 + s["drift"] * t)
                                         + 0.25 * math.sin(w * 6.3 - depth * 2.2 - s["drift"] * 0.6 * t))
             + 0.012 * math.sin(u * 22 + i * 0.7 + t) + scene["ripple"]["height"] * bump)
        points.append([x, y, z])
    level = (0.07 + 0.26 * math.sin(math.pi * depth) ** 2) * (1 + 1.6 * peak)
    return {"points": points, "level": level}
