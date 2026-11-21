# Set A, "Never pick up your phone": the phone sits on its stand beside the laptop and
# everything it asks for is handled on the laptop's real Saiph screens: a sign-in code, a
# text, a call, its screen in a window and its camera as the webcam. The camera cuts
# between the two so each action on the laptop is seen landing on the phone, and a pulse
# runs along the Saiph string whichever way it goes.
#
#   blender -b --factory-startup -P docs/marketing/2026-10-ad-sets/blender/set_a.py -- \
#       --laptop build/ad-sets/a/laptop --phone build/ad-sets/a/phone --out build/ad-sets/a/render --format story
import math
import os
import sys

import bmesh
import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kit as K  # noqa: E402

arg = K.args()
FPS, DURATION = 30, 26
FORMATS = {"story": (1080, 1920), "portrait": (1080, 1350), "square": (1080, 1080)}
fmt = arg("--format", "story")
kit = K.Kit()
waves = kit.desk()

laptop, hinge, screen = kit.laptop("laptop", os.path.abspath(arg("--laptop", "build/ad-sets/a/laptop")))
LAPTOP = K.pose((0.05, 0, 0), (0, -0.08, 0))
laptop.matrix_basis = LAPTOP
kit.keyboard(laptop, 0.015, -0.215 * 0.17)
LID = LAPTOP @ hinge.matrix_basis
NORMAL = (LID.to_3x3() @ Vector((0, 0, 1))).normalized()

# The phone on its stand, leaning back toward the viewer, never touched.
phone = kit.phone("phone", os.path.abspath(arg("--phone", "build/ad-sets/a/phone")))
PHONE = Matrix.Translation((-0.31, 0.078, 0.03)) @ Matrix.Rotation(0.38, 4, "Y") @ Matrix.Rotation(-0.28, 4, "X")
stand = kit.box("stand", (0.07, 0.012, 0.06), 0.003, kit.principled("stand", K.srgb("#1b2333"), 0.4, 0.5))
stand.matrix_basis = K.pose((-0.31, 0.006, 0.05), (0, 0.38, 0))
mug = kit.cylinder("mug", 0.04, 0.095, kit.principled("mug", K.srgb("#1e2a3d"), 0.25, coat=0.6))
mug.location = (0.42, 0.0475, -0.08)
book = kit.box("notebook", (0.15, 0.012, 0.21), 0.003, kit.principled("cover", K.srgb("#123c46"), 0.6))
book.matrix_basis = K.pose((0.3, 0.006, 0.27), (0, 0.3, 0))

# Buzzing: the phone shivers on its stand when something arrives; a call keeps ringing.
BUZZ = [(0.4, 0.9), (5.0, 5.5)] + [(10.0 + 1.0 * k, 10.55 + 1.0 * k) for k in range(3)]


def phone_matrix(t):
    on = any(a <= t < b for a, b in BUZZ)
    shake = Vector((0.0005 * math.sin(2 * math.pi * 23 * t), 0.0002 * math.sin(2 * math.pi * 17 * t), 0)) if on else Vector()
    return PHONE @ Matrix.Translation(shake)


# --- The Saiph string between them, with a pulse for each hand-off ----------------
string = kit.curve("string", [[0, 0, 0]] * 121, 0.0013, kit.line("string", 2.6))
bead_mesh = bpy.data.meshes.new("bead")
bm = bmesh.new()
bmesh.ops.create_uvsphere(bm, u_segments=20, v_segments=12, radius=0.005)
bm.to_mesh(bead_mesh)
bm.free()
bead_mesh.materials.append(kit.emission("bead", K.srgb("#67e8f9"), 30))
bead = kit.link(bpy.data.objects.new("bead", bead_mesh))
P0 = PHONE @ Vector((0, 0.088, 0.0))
P1 = LID @ Vector((-0.08, 0.205 / 2 + 0.006, 0.006))
# (start, direction): +1 phone to laptop, -1 laptop to phone. Each run takes 0.45 s.
PULSES = [(1.0, 1), (5.05, 1), (8.3, -1), (10.05, 1), (12.9, -1), (15.2, -1), (15.45, 1), (16.45, -1), (19.8, -1), (20.05, 1)]
RUN = 0.45


def string_point(s, t):
    mid = (P0 + P1) / 2 + Vector((0, 0.07, 0.02))
    base = P0 * (1 - s) ** 2 + mid * 2 * s * (1 - s) + P1 * s * s
    rings = [t - (a + RUN) for a, _ in PULSES if t >= a + RUN]
    since = min(rings) if rings else None
    ring = 0.0 if since is None else 0.003 * math.exp(-2.2 * since) * math.sin(math.pi * s) * math.sin(2 * math.pi * 3.0 * since)
    return base + Vector((0, ring, 0))


# --- Light and camera ------------------------------------------------------------
lamp = kit.light("lamp", "AREA", K.srgb("#ffd7a6"), 30, (-0.5, 0.7, 0.4), target=(0, 0.05, 0), size=0.45)
lamp.visible_glossy = False
kit.light("fill", "AREA", K.srgb("#9ecbff"), 8, (0.7, 0.45, 0.6), target=(-0.1, 0.1, 0), size=0.8)
kit.light("rim_violet", "AREA", K.srgb("#a78bfa"), 16, (0.6, 0.35, -0.45), target=(0.1, 0.1, -0.1), size=0.4)
kit.light("rim_cyan", "AREA", K.srgb("#22d3ee"), 6, (-0.6, 0.4, -0.4), target=(-0.3, 0.12, 0), size=0.3)
cam = kit.camera(hfov=0.62, fstop=3.5)


def screen_view(u, v, dist, yaw=0.0, pitch=0.06):
    look = LID @ Vector(((u - 0.5) * 0.288, 0.205 / 2 + 0.006 + (0.5 - v) * 0.18, 0.0064))
    az = math.atan2(NORMAL.x, NORMAL.z) + yaw
    el = math.asin(NORMAL.y) + pitch
    return look + Vector((math.sin(az) * math.cos(el), math.sin(el), math.cos(az) * math.cos(el))) * dist, look


def phone_view(u, v, dist, side=0.0):
    look = PHONE @ Vector(((u - 0.5) * 0.0715, (0.5 - v) * 0.1565, 0.0041))
    n = (PHONE.to_3x3() @ Vector((0, 0, 1))).normalized()
    return look + n * dist + Vector((side, 0.01, 0)), look


V = Vector
BOTH = V((-0.2, 0.11, -0.01))  # between the phone and the left of the laptop screen
SHOTS = [
    (0.0, 1.4, phone_view(0.5, 0.45, 0.21), phone_view(0.5, 0.45, 0.18)),          # code arrives on the phone
    (1.4, 4.7, screen_view(0.6, 0.55, 0.39), screen_view(0.6, 0.55, 0.35)),        # ...and on the PC, typed in
    (4.7, 5.9, phone_view(0.5, 0.48, 0.20), phone_view(0.5, 0.48, 0.18)),          # a text arrives
    (5.9, 8.45, screen_view(0.66, 0.66, 0.36), screen_view(0.66, 0.68, 0.33)),     # reply typed on the PC
    (8.45, 10.0, phone_view(0.5, 0.5, 0.30, 0.05), phone_view(0.5, 0.5, 0.24, 0.03)),  # the reply lands on the phone
    (10.0, 11.4, phone_view(0.5, 0.4, 0.21), phone_view(0.5, 0.4, 0.19)),          # a call rings
    (11.4, 13.0, screen_view(0.7, 0.25, 0.31), screen_view(0.72, 0.22, 0.29)),     # declined from the PC
    (13.0, 14.6, (V((-0.17, 0.21, 0.56)), BOTH), (V((-0.18, 0.2, 0.5)), BOTH)),  # phone goes quiet
    (14.6, 15.6, screen_view(0.5, 0.32, 0.36), screen_view(0.48, 0.34, 0.34)),     # Mirror screen
    (15.6, 18.2, (V((-0.18, 0.2, 0.56)), BOTH), (V((-0.19, 0.19, 0.47)), BOTH)),   # same screen in both places
    (18.2, 19.4, phone_view(0.5, 0.45, 0.21), phone_view(0.5, 0.45, 0.19)),        # scrolled from the PC
    (19.4, 20.5, screen_view(0.62, 0.45, 0.38), screen_view(0.62, 0.45, 0.36)),    # Webcam
    (20.5, 21.5, phone_view(0.5, 0.3, 0.2), phone_view(0.5, 0.3, 0.18)),           # camera in use
    (21.5, 23.4, screen_view(0.5, 0.45, 0.44), screen_view(0.5, 0.45, 0.41)),      # the call sees the phone's camera
    (23.4, 26.01, (V((0.1, 0.36, 0.78)), V((-0.08, 0.08, -0.05))), (V((0.08, 0.42, 0.9)), V((-0.08, 0.08, -0.05)))),
]


def frame(t):
    phone.matrix_basis = phone_matrix(t)
    reach = K.smooth((t - 0.2) / 0.6)
    pts = [string_point(min(k / 120, reach), t) for k in range(121)]
    K.set_points(string, [list(p) for p in pts])
    run = next(((a, d) for a, d in PULSES if a <= t < a + RUN), None)
    bead.hide_render = run is None
    if run:
        u = K.smooth((t - run[0]) / RUN)
        bead.location = string_point(u if run[1] > 0 else 1 - u, t)
    landed = [(a + RUN, d) for a, d in PULSES if t >= a + RUN]
    pluck = None
    if landed:
        at, d = landed[-1]
        pluck = (at, -0.3 if d > 0 else 0.05, 0.3)
    waves(t, pluck)
    pos, look = K.glide(SHOTS, t, shot_pose)
    K.aim(cam, list(pos), list(look))


def shot_pose(shot, t):
    a, b, start, end = shot
    u = K.smooth((t - a) / (b - a)) * 0.5 + 0.5 * K.clamp((t - a) / (b - a))
    return start[0].lerp(end[0], u), start[1].lerp(end[1], u)


kit.on_frame(frame)
kit.install(FPS)
width, height = FORMATS[fmt]
kit.setup_render(width, height, FPS, int(arg("--samples", "64")))
out_dir = os.path.abspath(os.path.join(arg("--out", "build/ad-sets/a/render"), fmt))
if arg("--time"):
    kit.render(out_dir, [round(float(arg("--time")) * FPS)], f"still-{arg('--time')}")
else:
    a, _, b = arg("--frames", f"0-{FPS * DURATION - 1}").partition("-")
    kit.render(out_dir, list(range(int(a), int(b or a) + 1)), None)
