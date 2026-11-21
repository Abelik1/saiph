# Set B, "Ctrl+V": copy on the phone, paste on the PC, and back, cut as macro close-ups
# of the phone screen, backlit keys and the laptop screen.
#
#   blender -b --factory-startup -P docs/marketing/2026-10-ad-sets/blender/set_b.py -- \
#       --phone build/ad-sets/b/phone --laptop build/ad-sets/b/laptop --out build/ad-sets/b/render --format story
import math
import os
import sys

from mathutils import Matrix, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kit as K  # noqa: E402

arg = K.args()
FPS, DURATION = 30, 12
FORMATS = {"story": (1080, 1920), "portrait": (1080, 1350), "square": (1080, 1080)}
fmt = arg("--format", "story")
kit = K.Kit()
waves = kit.desk()

laptop, hinge, screen = kit.laptop("laptop", os.path.abspath(arg("--laptop", "build/ad-sets/b/laptop")))
LAPTOP = K.pose((0.03, 0, 0), (0, -0.12, 0))
laptop.matrix_basis = LAPTOP
keys = kit.keyboard(laptop, 0.015, -0.215 * 0.17)

phone = kit.phone("phone", os.path.abspath(arg("--phone", "build/ad-sets/b/phone")))
PHONE = Matrix.Translation((-0.25, 0.0042, 0.07)) @ Matrix.Rotation(0.22, 4, "Y") @ Matrix.Rotation(-math.pi / 2, 4, "X")
phone.matrix_basis = PHONE

lamp = kit.light("lamp", "AREA", K.srgb("#ffd7a6"), 34, (-0.5, 0.7, 0.4), target=(0, 0.05, 0), size=0.45)
lamp.visible_glossy = False
kit.light("fill", "AREA", K.srgb("#9ecbff"), 6, (0.7, 0.4, 0.6), target=(0, 0.08, 0), size=0.8)
kit.light("rim_violet", "AREA", K.srgb("#a78bfa"), 14, (0.6, 0.35, -0.45), target=(0.1, 0.1, -0.1), size=0.4)
kit.light("rim_cyan", "AREA", K.srgb("#22d3ee"), 1.6, (-0.7, 0.45, -0.6), target=(0, 0.2, -0.15), size=0.4)

cam = kit.camera(hfov=0.62, fstop=4.0)
LID = LAPTOP @ hinge.matrix_basis
NORMAL = (LID.to_3x3() @ Vector((0, 0, 1))).normalized()


def screen_point(u, v):
    return LID @ Vector(((u - 0.5) * 0.288, 0.205 / 2 + 0.006 + (0.5 - v) * 0.18, 0.0064))


def screen_view(u, v, dist, yaw=0.0, pitch=0.06):
    look = screen_point(u, v)
    az = math.atan2(NORMAL.x, NORMAL.z) + yaw
    el = math.asin(NORMAL.y) + pitch
    return look + Vector((math.sin(az) * math.cos(el), math.sin(el), math.cos(az) * math.cos(el))) * dist, look


def phone_point(u, v):
    return PHONE @ Vector(((u - 0.5) * 0.0715, (0.5 - v) * 0.1565, 0.0041))


def phone_view(u, v, height):
    look = phone_point(u, v)
    return look + Vector((0.0, height, height * 0.32)), look


def key_point(label):
    key, rest = keys[label]
    return LAPTOP @ rest.translation


def key_view(label, side):
    look = key_point(label)
    return look + Vector((0.018 * side, 0.034, 0.066)), look


# Shots with hard cuts: (start, end, (pos, look) at start, (pos, look) at end).
def shot(a, b, start, end):
    return (a, b, start, end)


def drift(view, dpos):
    pos, look = view
    return pos + Vector(dpos), look


SHOTS = [
    shot(0.0, 2.0, phone_view(0.5, 0.3, 0.15), phone_view(0.5, 0.3, 0.125)),
    shot(2.0, 2.45, key_view("Ctrl", 1), drift(key_view("Ctrl", 1), (-0.006, -0.002, -0.004))),
    shot(2.45, 2.9, key_view("V", -1), drift(key_view("V", -1), (0.006, -0.002, -0.004))),
    shot(2.9, 4.0, screen_view(0.42, 0.33, 0.30), screen_view(0.42, 0.33, 0.27)),
    shot(4.0, 4.8, screen_view(0.32, 0.12, 0.25), screen_view(0.33, 0.12, 0.23)),
    shot(4.8, 5.35, key_view("C", 1), drift(key_view("C", 1), (-0.006, -0.002, -0.004))),
    shot(5.35, 7.0, phone_view(0.5, 0.62, 0.17), phone_view(0.5, 0.62, 0.145)),
    shot(7.0, 7.9, phone_view(0.5, 0.42, 0.16), phone_view(0.5, 0.42, 0.14)),
    shot(7.9, 8.3, key_view("V", 1), drift(key_view("V", 1), (-0.006, -0.002, -0.004))),
    shot(8.3, 9.6, screen_view(0.5, 0.45, 0.33), screen_view(0.5, 0.45, 0.42)),
    shot(9.6, 12.01, (Vector((0.02, 0.40, 0.70)), Vector((-0.07, 0.06, -0.02))), (Vector((0.0, 0.46, 0.82)), Vector((-0.07, 0.06, -0.02)))),
]

# Key presses: (label, down, up).
PRESSES = [("Ctrl", 2.1, 2.95), ("V", 2.6, 2.8), ("Ctrl", 4.85, 5.35), ("C", 4.97, 5.15), ("Ctrl", 7.95, 8.32), ("V", 8.06, 8.22)]
PASTES = [3.05, 6.15, 8.4]


def press_depth(label, t):
    depth = 0.0
    for name, down, up in PRESSES:
        if name == label and down - 0.05 <= t <= up + 0.06:
            depth = max(depth, K.smooth((t - down + 0.05) / 0.05) * (1 - K.smooth((t - up) / 0.06)))
    return depth


def frame(t):
    for label in ("Ctrl", "V", "C"):
        key, rest = keys[label]
        key.matrix_basis = Matrix.Translation((0, -0.0012 * press_depth(label, t), 0)) @ rest
    pluck = max([p for p in PASTES if p <= t], default=None)
    waves(t, (pluck, -0.1, 0.4) if pluck is not None else None)
    for a, b, start, end in SHOTS:
        if a <= t < b:
            u = K.smooth((t - a) / (b - a)) * 0.5 + 0.5 * ((t - a) / (b - a))
            pos = start[0].lerp(end[0], u)
            look = start[1].lerp(end[1], u)
            K.aim(cam, list(pos), list(look))
            break


kit.on_frame(frame)
kit.install(FPS)
width, height = FORMATS[fmt]
kit.setup_render(width, height, FPS, int(arg("--samples", "64")))
out_dir = os.path.abspath(os.path.join(arg("--out", "build/ad-sets/b/render"), fmt))
if arg("--time"):
    kit.render(out_dir, [round(float(arg("--time")) * FPS)], f"still-{arg('--time')}")
else:
    a, _, b = arg("--frames", f"0-{FPS * DURATION - 1}").partition("-")
    kit.render(out_dir, list(range(int(a), int(b or a) + 1)), None)
