# Set C, "Enough.": the rituals (email to yourself, a walk across the room for the phone
# holding a sign-in code, a link typed by hand), then an address is copied on the phone and
# its pulse shatters the pane of glass between phone and laptop in slow motion. The address
# is pasted on the PC, and the next code arrives on the phone and goes straight to the PC.
#
#   blender -b --factory-startup -P docs/marketing/2026-10-ad-sets/blender/set_c.py -- \
#       --laptop build/ad-sets/c/laptop --phone build/ad-sets/c/phone --far build/ad-sets/c/phone-far/0000.png \
#       --out build/ad-sets/c/render --format story
import math
import os
import random
import sys

import bmesh
import bpy
from mathutils import Matrix, Quaternion, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kit as K  # noqa: E402

arg = K.args()
FPS, DURATION = 30, 17.5
FORMATS = {"story": (1080, 1920), "portrait": (1080, 1350), "square": (1080, 1080)}
fmt = arg("--format", "story")
kit = K.Kit()
waves = kit.desk()

laptop, hinge, screen = kit.laptop("laptop", os.path.abspath(arg("--laptop", "build/ad-sets/c/laptop")))
LAPTOP = K.pose((0.05, 0, 0), (0, -0.08, 0))
laptop.matrix_basis = LAPTOP
kit.keyboard(laptop, 0.015, -0.215 * 0.17)
LID = LAPTOP @ hinge.matrix_basis
NORMAL = (LID.to_3x3() @ Vector((0, 0, 1))).normalized()

# --- The room: floor, walls, a bookcase across the room holding the phone ----------
FLOOR = -0.75
floor = kit.plane("floor", 7.0, 5.0, kit.principled("floor", K.srgb("#2a1c12"), 0.55, coat=0.15))
floor.matrix_basis = Matrix.Translation((-1.0, FLOOR, 0.9)) @ Matrix.Rotation(-math.pi / 2, 4, "X")
paint = kit.principled("paint", K.srgb("#0b1018"), 0.85)
kit.plane("back_wall", 6.0, 2.7, paint).location = (-1.0, 0.55, -0.79)
side = kit.plane("side_wall", 5.0, 2.7, paint)
side.matrix_basis = Matrix.Translation((-3.0, 0.55, 0.9)) @ Matrix.Rotation(math.pi / 2, 4, "Y")
dark = kit.principled("desk_frame", K.srgb("#15100c"), 0.5)
kit.box("desk_body", (2.4, 0.04, 1.4), 0.004, dark).location = (0, -0.021, -0.1)
for x in (-1.15, 1.15):
    kit.box("desk_leg", (0.04, 0.71, 1.2), 0.004, dark).location = (x, FLOOR / 2 - 0.02, -0.1)
kit.box("rug", (1.9, 0.01, 1.3), 0.004, kit.principled("rug", K.srgb("#173a44"), 0.95)).location = (-1.7, FLOOR + 0.005, 0.55)
kit.plane("window", 0.9, 1.2, kit.emission("window", K.srgb("#1e3a5f"), 1.6)).location = (-1.9, 0.6, -0.785)
for size in ((0.03, 1.2, 0.02), (0.9, 0.03, 0.02)):
    kit.box("window_bar", size, 0.002, dark).location = (-1.9, 0.6, -0.78)
shelf_mat = kit.principled("shelf", K.srgb("#2a1d14"), 0.5)
for y in (-0.72, -0.3, 0.1, 0.5, 0.85):
    kit.box("shelf", (0.35, 0.025, 0.9), 0.003, shelf_mat).location = (-2.82, y, 0.25)
for z in (-0.2, 0.7):
    kit.box("shelf_side", (0.35, 1.6, 0.025), 0.003, shelf_mat).location = (-2.82, FLOOR + 0.8, z)
book_rng = random.Random(3)
BOOK_COLOURS = ["#4a2424", "#24304f", "#22402c", "#4f3a22", "#2c3542", "#3d2c52", "#1f4744", "#5a3420"]
for y0 in (-0.7075, -0.2875, 0.1125, 0.5125):
    z = -0.17
    while z < 0.66:
        w, h = book_rng.uniform(0.022, 0.045), book_rng.uniform(0.18, 0.3)
        if y0 == 0.1125 and 0.12 < z < 0.4:
            z += w  # the phone's spot
            continue
        kit.box("book", (book_rng.uniform(0.18, 0.24), h, w), 0.002,
                kit.principled("book", K.srgb(book_rng.choice(BOOK_COLOURS)), 0.7)).location = (-2.86, y0 + h / 2, z + w / 2)
        z += w + 0.004
kit.cylinder("lamp_pole", 0.012, 1.45, dark).location = (-2.55, FLOOR + 0.725, -0.45)
kit.cylinder("lamp_shade", 0.16, 0.24, kit.emission("lamp_shade", K.srgb("#ffcf8a"), 4.0)).location = (-2.55, FLOOR + 1.5, -0.45)
kit.cylinder("pot", 0.13, 0.32, kit.principled("pot", K.srgb("#334155"), 0.6)).location = (-2.45, FLOOR + 0.16, 1.0)
leaf_rng = random.Random(5)
for i in range(9):
    leaf = kit.box("leaf", (0.05, 0.42, 0.012), 0.006, kit.principled("leaf", K.srgb("#1f5130"), 0.6))
    leaf.matrix_basis = K.pose((-2.45, FLOOR + 0.5, 1.0), (leaf_rng.uniform(-0.5, 0.5), i * 0.7, leaf_rng.uniform(-0.5, 0.5)))

# The phone across the room, propped against the books, holding the code.
far = kit.phone("far_phone", os.path.abspath(arg("--far", "build/ad-sets/c/phone-far/0000.png")))
FAR_PHONE = Matrix.Translation((-2.74, 0.1125 + 0.079, 0.26)) @ Matrix.Rotation(0.22, 4, "Z") @ Matrix.Rotation(math.pi / 2, 4, "Y")
FAR_BUZZ = [(2.3, 2.8), (3.5, 4.0)]

# The phone on the desk, leaning back on a small stand, facing the camera side.
desk_phone = kit.phone("desk_phone", os.path.abspath(arg("--phone", "build/ad-sets/c/phone")))
DESK_PHONE = Matrix.Translation((-0.31, 0.078, 0.03)) @ Matrix.Rotation(0.38, 4, "Y") @ Matrix.Rotation(-0.28, 4, "X")
desk_phone.matrix_basis = DESK_PHONE
stand = kit.box("stand", (0.07, 0.012, 0.06), 0.003, kit.principled("stand", K.srgb("#1b2333"), 0.4, 0.5))
stand.matrix_basis = K.pose((-0.31, 0.006, 0.05), (0, 0.38, 0))

# --- The pane and its shards ----------------------------------------------------
PANE_X, PANE_H, PANE_W, PANE_T = -0.17, 0.30, 0.34, 0.005
IMPACT = Vector((PANE_X, 0.17, 0.01))
SHATTER = 8.55
glass = kit.principled("glass", K.srgb("#d8f6ff"), 0.03, 0.0, coat=0.0, **{"Transmission Weight": 1.0, "IOR": 1.45})
rng = random.Random(7)
seeds = []
while len(seeds) < 46:
    # Denser near the impact, where real glass breaks into smaller pieces.
    r = abs(rng.gauss(0, 0.09)) if len(seeds) < 30 else rng.uniform(0, 0.25)
    a = rng.uniform(0, 2 * math.pi)
    y, z = IMPACT.y + r * math.sin(a), IMPACT.z + r * math.cos(a) * 1.2
    if 0.004 < y < PANE_H - 0.004 and abs(z) < PANE_W / 2 - 0.004:
        seeds.append(Vector((0, y, z)))

shards = []
for i, seed in enumerate(seeds):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co = Vector((v.co.x * PANE_T, v.co.y * PANE_H + PANE_H / 2, v.co.z * PANE_W))
    for j, other in enumerate(seeds):
        if i == j:
            continue
        mid, normal = (seed + other) / 2, (other - seed).normalized()
        geom = bm.verts[:] + bm.edges[:] + bm.faces[:]
        cut = bmesh.ops.bisect_plane(bm, geom=geom, plane_co=mid, plane_no=normal, clear_outer=True)
        edges = [e for e in cut["geom_cut"] if isinstance(e, bmesh.types.BMEdge)]
        if edges:
            bmesh.ops.holes_fill(bm, edges=edges, sides=0)
    if not bm.verts:
        bm.free()
        continue
    centre = sum((v.co for v in bm.verts), Vector()) / len(bm.verts)
    for v in bm.verts:
        v.co -= centre
    mesh = bpy.data.meshes.new(f"shard_{i:02d}")
    bm.to_mesh(mesh)
    bm.free()
    mesh.materials.append(glass)
    obj = kit.link(bpy.data.objects.new(f"shard_{i:02d}", mesh))
    rest = Vector((PANE_X, 0, 0)) + centre
    away = Vector((0, centre.y - IMPACT.y, centre.z - IMPACT.z))
    near = math.exp(-away.length / 0.12)
    velocity = (away.normalized() if away.length else Vector((0, 1, 0))) * (0.12 + 0.55 * near * rng.uniform(0.6, 1.2))
    velocity.x = rng.choice((-1, 1)) * rng.uniform(0.05, 0.25) + 0.15 * near
    spin_axis = Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1))).normalized()
    shards.append((obj, rest, velocity, spin_axis, rng.uniform(2, 9) * (0.5 + near)))

flash = kit.light("flash", "POINT", K.srgb("#9ff3ff"), 0, tuple(IMPACT))

# --- The Saiph string from the phone to the laptop --------------------------------
string = kit.curve("string", [[0, 0, 0]] * 121, 0.0016, kit.line("string", 4.0))
bead_mesh = bpy.data.meshes.new("bead")
bm = bmesh.new()
bmesh.ops.create_uvsphere(bm, u_segments=20, v_segments=12, radius=0.006)
bm.to_mesh(bead_mesh)
bm.free()
bead_mesh.materials.append(kit.emission("bead", K.srgb("#67e8f9"), 30))
bead = kit.link(bpy.data.objects.new("bead", bead_mesh))
P0 = DESK_PHONE @ Vector((0, 0.088, 0.0))
P1 = LID @ Vector((-0.06, 0.205 / 2 + 0.006, 0.006))
PLUCK = 8.0          # the copy's pulse leaves the phone
SLOW = 0.3           # the shards fall in slow motion once the glass breaks
# The pulse runs phone to laptop in one eased move, passing the pane (45% of the way,
# eased time 0.4667) exactly as it shatters, so it never pauses at the glass.
ARRIVE = PLUCK + (SHATTER - PLUCK) / 0.4667
CODE = 13.75         # the next code leaves the phone for the laptop


def string_point(s, t):
    mid = (P0 + P1) / 2 + Vector((0, 0.07, 0.02))
    return P0 * (1 - s) ** 2 + mid * 2 * s * (1 - s) + P1 * s * s


def frame(t):
    before = t < 4.6
    buzz = any(a <= t < b for a, b in FAR_BUZZ)
    far.matrix_basis = FAR_PHONE @ Matrix.Translation((0.0006 * math.sin(2 * math.pi * 23 * t) if buzz else 0, 0, 0))
    for obj in K_children(far):
        obj.hide_render = not before
    for obj in K_children(desk_phone) + [stand]:
        obj.hide_render = before
    near = 13.4 <= t < 13.9
    desk_phone.matrix_basis = DESK_PHONE @ Matrix.Translation((0.0005 * math.sin(2 * math.pi * 23 * t) if near else 0, 0, 0))
    # String: grows from the phone with the copy, stops at the pane, and reaches the
    # laptop once the glass breaks.
    string.hide_render = t < PLUCK
    reach = K.smooth((t - PLUCK) / (ARRIVE - PLUCK))
    pts = [string_point(min(k / 120, reach) if reach > 0 else 0.0, t) for k in range(121)]
    K.set_points(string, [list(p) for p in pts])
    if PLUCK <= t < ARRIVE + 0.1:
        bead.hide_render = False
        bead.location = string_point(reach, t)
    elif CODE <= t < CODE + 0.45:
        bead.hide_render = False
        bead.location = string_point(K.smooth((t - CODE) / 0.45), t)
    else:
        bead.hide_render = True
    flash.data.energy = 6.0 * math.exp(-((t - SHATTER) / 0.12) ** 2) if t >= SHATTER - 0.1 else 0.0
    # Shards: whole until the pulse arrives, then a slow-motion burst.
    s = max(0.0, t - SHATTER) * SLOW
    for obj, rest, velocity, axis, spin in shards:
        obj.hide_render = t > SHATTER + 3.3 or t < 4.6
        pos = rest + velocity * s + Vector((0, -0.5 * 0.9 * s * s, 0))
        obj.matrix_basis = Matrix.Translation(pos) @ Quaternion(axis, spin * s).to_matrix().to_4x4()
    pluck = max([p for p in (SHATTER, ARRIVE, CODE + 0.45) if p <= t], default=None)
    waves(t, (pluck, -0.17, 0.4) if pluck else None)
    # A straight cut back to the desk after the walk: gliding 2.5 m in a blink reads as a jolt.
    # The turn sweeps across the desk, where the cyan rim light shows as a big glossy patch.
    rim_cyan.visible_glossy = not 1.5 <= t < 4.6
    pos, look = K.glide(SHOTS, t, shot_pose, hard={4.6})
    K.aim(cam, list(pos), list(look))


def walk_pose(t):
    """Lean back from the laptop and turn to the phone across the room, hold on it while it
    buzzes, then one smooth move up to the shelf."""
    turn = K.smooth((t - WALK_TURN[0]) / (WALK_TURN[1] - WALK_TURN[0]))
    move = K.smooth((t - WALK_MOVE[0]) / (WALK_MOVE[1] - WALK_MOVE[0]))
    far = Vector(FAR)
    pos = SEAT.lerp(SHELF, move)
    to_far = far - SEAT
    look = SEAT + (DESK_LOOK - SEAT).normalized().slerp(to_far.normalized(), turn) * to_far.length
    return pos, look if turn < 1 else far


def shot_pose(shot, t):
    a, b, start, end = shot
    if start == "walk":
        return walk_pose(t)
    u = K.smooth((t - a) / (b - a)) * 0.5 + 0.5 * K.clamp((t - a) / (b - a))
    return start[0].lerp(end[0], u), start[1].lerp(end[1], u)


def K_children(obj):
    return [obj] + [c for c in obj.children_recursive]


# --- Light and camera ------------------------------------------------------------
lamp = kit.light("lamp", "AREA", K.srgb("#ffd7a6"), 30, (-0.5, 0.7, 0.4), target=(0, 0.05, 0), size=0.45)
lamp.visible_glossy = False
kit.light("fill", "AREA", K.srgb("#9ecbff"), 8, (0.7, 0.45, 0.6), target=(-0.1, 0.1, 0), size=0.8)
kit.light("rim_violet", "AREA", K.srgb("#a78bfa"), 16, (0.6, 0.35, -0.45), target=(0.1, 0.1, -0.1), size=0.4)
rim_cyan = kit.light("rim_cyan", "AREA", K.srgb("#22d3ee"), 10, (-0.6, 0.4, -0.4), target=(-0.17, 0.15, 0), size=0.3)
kit.light("room_lamp", "POINT", K.srgb("#ffcf8a"), 40, (-2.55, FLOOR + 1.35, -0.45))
kit.light("shelf_light", "AREA", K.srgb("#ffd7a6"), 6, (-2.3, 0.6, 0.3), target=(-2.8, 0.15, 0.25), size=0.3)
cam = kit.camera(hfov=0.62, fstop=3.2)


def screen_view(u, v, dist, yaw=0.0, pitch=0.06):
    look = LID @ Vector(((u - 0.5) * 0.288, 0.205 / 2 + 0.006 + (0.5 - v) * 0.18, 0.0064))
    az = math.atan2(NORMAL.x, NORMAL.z) + yaw
    el = math.asin(NORMAL.y) + pitch
    return look + Vector((math.sin(az) * math.cos(el), math.sin(el), math.cos(az) * math.cos(el))) * dist, look


def phone_view(u, v, dist):
    look = DESK_PHONE @ Vector(((u - 0.5) * 0.0715, (0.5 - v) * 0.1565, 0.0041))
    n = (DESK_PHONE.to_3x3() @ Vector((0, 0, 1))).normalized()
    return look + n * dist + Vector((0, 0.01, 0)), look


V = Vector
FAR = list(FAR_PHONE @ Vector((0, 0.01, 0)))
# The walk: from the chair, turn to the phone on the shelf, wait, then cross the room to it.
SEAT, SHELF, DESK_LOOK = V((0.0, 0.36, 0.6)), V((-2.3, 0.33, 0.3)), V((0.04, 0.12, -0.06))
WALK_TURN, WALK_MOVE = (1.9, 2.75), (3.15, 4.6)
SHOTS = [
    (0.0, 1.8, screen_view(0.45, 0.42, 0.33), screen_view(0.45, 0.42, 0.29)),        # emailed yourself a link
    (1.8, 4.6, "walk", None),                                                          # across the room for a code
    (4.6, 6.2, screen_view(0.3, 0.12, 0.25), screen_view(0.34, 0.12, 0.22)),          # typed by hand
    (6.2, 8.0, phone_view(0.5, 0.33, 0.15), phone_view(0.5, 0.33, 0.13)),             # copy on the phone
    (8.0, 11.85, (V((0.40, 0.30, 0.52)), V((-0.15, 0.13, -0.01))), (V((-0.02, 0.2, 0.33)), V((-0.17, 0.15, 0.0)))),  # Enough.
    (11.85, 13.4, screen_view(0.4, 0.33, 0.30), screen_view(0.4, 0.33, 0.27)),        # Ctrl+V
    (13.4, 14.15, phone_view(0.5, 0.06, 0.16), phone_view(0.5, 0.06, 0.14)),          # the code lands on the phone
    (14.15, 15.6, screen_view(0.6, 0.55, 0.38), screen_view(0.6, 0.55, 0.35)),        # ...and on the PC
    (15.6, 17.51, (V((0.12, 0.34, 0.72)), V((-0.08, 0.08, -0.05))), (V((0.1, 0.40, 0.84)), V((-0.08, 0.08, -0.05)))),
]

kit.on_frame(frame)
kit.install(FPS)
width, height = FORMATS[fmt]
kit.setup_render(width, height, FPS, int(arg("--samples", "64")))
bpy.context.scene.cycles.transmission_bounces = 8
out_dir = os.path.abspath(os.path.join(arg("--out", "build/ad-sets/c/render"), fmt))
if arg("--time"):
    kit.render(out_dir, [round(float(arg("--time")) * FPS)], f"still-{arg('--time')}")
else:
    a, _, b = arg("--frames", f"0-{round(FPS * DURATION) - 1}").partition("-")
    kit.render(out_dir, list(range(int(a), int(b or a) + 1)), None)
