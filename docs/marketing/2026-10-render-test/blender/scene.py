# Blender renderer for the comparison. Builds the scene from ../scene.json and
# renders frames headless; no window opens.
#
#   blender -b --factory-startup -P docs/marketing/2026-10-render-test/blender/scene.py -- \
#       --out build/render-test --format story|still [--frames 0-299] [--samples 64] [--engine CYCLES|EEVEE]
import json
import math
import os
import sys
import time

import bmesh
import bpy
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import motion as m  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
def arg(name, default=None):
    return argv[argv.index(name) + 1] if name in argv else default

SPEC = json.load(open(os.path.join(ROOT, "scene.json"), encoding="utf-8"))
FORMAT = arg("--format", "story")
OUT = os.path.abspath(arg("--out", "build/render-test"))
ENGINE = arg("--engine", "CYCLES")
SAMPLES = int(arg("--samples", "64"))
FPS = SPEC["fps"]


def srgb(hex_color, scale=1.0):
    """Hex sRGB colour as linear RGBA, which Blender's colour sockets expect."""
    def lin(c):
        c = int(c, 16) / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    h = hex_color.lstrip("#")
    return (lin(h[0:2]) * scale, lin(h[2:4]) * scale, lin(h[4:6]) * scale, 1.0)


def euler_xyz(r):
    """three.js 'XYZ' Euler order: R = Rx * Ry * Rz."""
    return Matrix.Rotation(r[0], 4, "X") @ Matrix.Rotation(r[1], 4, "Y") @ Matrix.Rotation(r[2], 4, "Z")


def pose_matrix(position, rotation):
    return Matrix.Translation(Vector(position)) @ euler_xyz(rotation)


# --- Clean slate -----------------------------------------------------------
for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)
scene = bpy.context.scene
collection = scene.collection

# Everything hangs off one empty rotated +90 deg about X, so children use three.js axes.
root = bpy.data.objects.new("three_space", None)
root.rotation_euler = (math.pi / 2, 0, 0)
collection.objects.link(root)


def link(obj, parent=root):
    collection.objects.link(obj)
    obj.parent = parent
    return obj


# --- Materials -------------------------------------------------------------
def new_material(name):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    return mat, nodes, mat.node_tree.links, out


def body_material():
    mat, nodes, links, out = new_material("body")
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = srgb(SPEC["colors"]["body"])
    bsdf.inputs["Metallic"].default_value = 0.75
    bsdf.inputs["Roughness"].default_value = 0.3
    bsdf.inputs["Coat Weight"].default_value = 0.6
    bsdf.inputs["Coat Roughness"].default_value = 0.25
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


def flat_material(name, color, roughness=0.6, metallic=0.0):
    mat, nodes, links, out = new_material(name)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = color
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


def image(path):
    img = bpy.data.images.load(os.path.normpath(os.path.join(ROOT, path)), check_existing=True)
    img.colorspace_settings.name = "sRGB"
    return img


def screen_material(name, path, strength=0.92, second=None, glass=False):
    """Self-lit screen. With `second`, a Mix factor (node 'swap') blends the two images."""
    mat, nodes, links, out = new_material(name)
    tex = nodes.new("ShaderNodeTexImage")
    tex.image = image(path)
    tex.interpolation = "Cubic"
    color, alpha = tex.outputs["Color"], tex.outputs["Alpha"]
    if second:
        tex2 = nodes.new("ShaderNodeTexImage")
        tex2.image = image(second)
        tex2.interpolation = "Cubic"
        mix = nodes.new("ShaderNodeMix")
        mix.name = "swap"
        mix.data_type = "RGBA"
        links.new(tex.outputs["Color"], mix.inputs["A"])
        links.new(tex2.outputs["Color"], mix.inputs["B"])
        color = mix.outputs["Result"]
    emit = nodes.new("ShaderNodeEmission")
    emit.inputs["Strength"].default_value = strength
    links.new(color, emit.inputs["Color"])
    fade = nodes.new("ShaderNodeMath")
    fade.name = "opacity"
    fade.operation = "MULTIPLY"
    fade.inputs[1].default_value = 1.0
    links.new(alpha, fade.inputs[0])
    clear = nodes.new("ShaderNodeBsdfTransparent")
    mix_shader = nodes.new("ShaderNodeMixShader")
    links.new(fade.outputs[0], mix_shader.inputs["Fac"])
    links.new(clear.outputs["BSDF"], mix_shader.inputs[1])
    surface = emit.outputs["Emission"]
    if glass:
        gloss = nodes.new("ShaderNodeBsdfGlossy")
        gloss.inputs["Roughness"].default_value = 0.06
        fresnel = nodes.new("ShaderNodeLayerWeight")
        fresnel.inputs["Blend"].default_value = 0.12
        layer = nodes.new("ShaderNodeMixShader")
        links.new(fresnel.outputs["Fresnel"], layer.inputs["Fac"])
        links.new(emit.outputs["Emission"], layer.inputs[1])
        links.new(gloss.outputs["BSDF"], layer.inputs[2])
        surface = layer.outputs["Shader"]
    links.new(surface, mix_shader.inputs[2])
    links.new(mix_shader.outputs["Shader"], out.inputs["Surface"])
    return mat


def line_material(name, strength):
    """Emission along the string, cyan through light cyan to violet over its length."""
    mat, nodes, links, out = new_material(name)
    coords = nodes.new("ShaderNodeTexCoord")
    sep = nodes.new("ShaderNodeSeparateXYZ")
    links.new(coords.outputs["Generated"], sep.inputs["Vector"])
    ramp = nodes.new("ShaderNodeValToRGB")
    elements = ramp.color_ramp.elements
    elements[0].position, elements[0].color = 0.0, srgb(SPEC["colors"]["wave1"])
    elements[1].position, elements[1].color = 1.0, srgb(SPEC["colors"]["wave3"])
    mid = elements.new(0.45)
    mid.color = srgb(SPEC["colors"]["wave2"])
    links.new(sep.outputs["X"], ramp.inputs["Fac"])
    emit = nodes.new("ShaderNodeEmission")
    emit.name = "glow"
    emit.inputs["Strength"].default_value = strength
    links.new(ramp.outputs["Color"], emit.inputs["Color"])
    links.new(emit.outputs["Emission"], out.inputs["Surface"])
    return mat


def emission_material(name, color, strength):
    mat, nodes, links, out = new_material(name)
    emit = nodes.new("ShaderNodeEmission")
    emit.inputs["Color"].default_value = color
    emit.inputs["Strength"].default_value = strength
    links.new(emit.outputs["Emission"], out.inputs["Surface"])
    return mat


# --- Geometry --------------------------------------------------------------
def rounded_box(name, size, radius, material, segments=6):
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co = Vector((v.co.x * size[0], v.co.y * size[1], v.co.z * size[2]))
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    bevel = obj.modifiers.new("round", "BEVEL")
    bevel.width = radius
    bevel.segments = segments
    bevel.limit_method = "NONE"
    bevel.harden_normals = False
    mesh.materials.append(material)
    for poly in mesh.polygons:
        poly.use_smooth = True
    return obj


def plane(name, w, h, material):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(-w / 2, -h / 2, 0), (w / 2, -h / 2, 0), (w / 2, h / 2, 0), (-w / 2, h / 2, 0)], [], [(0, 1, 2, 3)])
    uv = mesh.uv_layers.new()
    for loop, co in zip(uv.data, [(0, 0), (1, 0), (1, 1), (0, 1)]):
        loop.uv = co
    mesh.materials.append(material)
    return bpy.data.objects.new(name, mesh)


def curve(name, points, radius, material):
    data = bpy.data.curves.new(name, "CURVE")
    data.dimensions = "3D"
    data.bevel_depth = radius
    data.bevel_resolution = 3
    data.use_fill_caps = True
    spline = data.splines.new("POLY")
    spline.points.add(len(points) - 1)
    data.materials.append(material)
    obj = bpy.data.objects.new(name, data)
    set_points(obj, points)
    return obj


def set_points(obj, points):
    for p, co in zip(obj.data.splines[0].points, points):
        p.co = (co[0], co[1], co[2], 1.0)


body = body_material()

# Phone.
phone = link(bpy.data.objects.new("phone", None))
pw, ph, pd = SPEC["phone"]["size"]
inset = SPEC["phone"]["screenInset"]
link(rounded_box("phone_body", SPEC["phone"]["size"], SPEC["phone"]["radius"], body), phone)
glass = link(plane("phone_screen", pw - inset * 2, ph - inset * 2, screen_material("phone_screen", SPEC["phone"]["screen"], glass=True)), phone)
glass.location = (0, 0, pd / 2 + 0.001)

# Laptop.
L = SPEC["laptop"]
laptop = link(bpy.data.objects.new("laptop", None))
bw, bh, bd = L["base"]
base = link(rounded_box("laptop_base", L["base"], L["radius"], body), laptop)
base.location = (0, bh / 2, 0)
well = link(plane("keyboard", bw * 0.86, bd * 0.42, flat_material("keyboard", srgb("#0b0f16"), 0.8)), laptop)
well.matrix_basis = Matrix.Translation((0, bh + 0.002, -bd * 0.16)) @ Matrix.Rotation(-math.pi / 2, 4, "X")
pad = link(plane("trackpad", bw * 0.3, bd * 0.26, flat_material("trackpad", srgb("#232c3b"), 0.45, 0.3)), laptop)
pad.matrix_basis = Matrix.Translation((0, bh + 0.002, bd * 0.26)) @ Matrix.Rotation(-math.pi / 2, 4, "X")
hinge = link(bpy.data.objects.new("hinge", None), laptop)
hinge.matrix_basis = Matrix.Translation((0, bh, -bd / 2)) @ Matrix.Rotation(m.lid_tilt(SPEC), 4, "X")
lw, lh, lt = L["lid"]
lid = link(rounded_box("lid", L["lid"], L["radius"] / 2, body), hinge)
lid.location = (0, lh / 2, lt / 2)
sw, sh = L["screenSize"]
laptop_screen_mat = screen_material("laptop_screen", L["screenBefore"], second=L["screen"], glass=True)
laptop_screen = link(plane("laptop_screen", sw, sh, laptop_screen_mat), hinge)
laptop_screen.location = m.screen_local(SPEC)

# Backdrop glow, as in the three.js version.
B = SPEC["backdrop"]
backdrop = link(plane("backdrop", B["size"][0], B["size"][1], screen_material("backdrop", B["image"], strength=1.0)))
backdrop.location = B["position"]

# Strings, the hero string, its light bead and the travelling photo.
S = SPEC["strings"]
floor = []
for i in range(S["count"]):
    state = m.floor_string(SPEC, 0, i)
    floor.append(link(curve(f"string_{i:02d}", state["points"], 0.006, line_material(f"string_{i:02d}", state["level"] * 3.2))))
hero_mat = line_material("hero", 1.6)
hero = link(curve("hero", [[0, 0, 0]] * 121, 0.013, hero_mat))
bead_mesh = bpy.data.meshes.new("bead")
bm = bmesh.new()
bmesh.ops.create_uvsphere(bm, u_segments=24, v_segments=16, radius=0.05)
bm.to_mesh(bead_mesh)
bm.free()
bead_mesh.materials.append(emission_material("bead", srgb(SPEC["colors"]["wave2"]), 8.0))
bead = link(bpy.data.objects.new("bead", bead_mesh))
card_mat = screen_material("card", SPEC["photo"]["image"], strength=0.8)
card = link(plane("card", 1, 1, card_mat))

# --- Light -----------------------------------------------------------------
def light(name, kind, color, energy, position, size=None):
    data = bpy.data.lights.new(name, kind)
    data.color = color[:3]
    data.energy = energy
    if size and kind == "AREA":
        data.size = size
    obj = link(bpy.data.objects.new(name, data))
    obj.location = position
    return obj

key = light("key", "SUN", (1, 1, 1), 2.2, (2, 6, 5))
key_dir = Vector((-2, -6, -5)).normalized()
key.matrix_basis = Matrix.Translation((2, 6, 5)) @ key_dir.to_track_quat("-Z", "Y").to_matrix().to_4x4()
light("cyan", "POINT", srgb(SPEC["colors"]["wave1"]), 1300, (-2.4, 0.9, 0.2))
light("violet", "POINT", srgb(SPEC["colors"]["wave3"]), 1600, (2.8, 1.6, -3.2))
soft = light("softbox", "AREA", (1, 1, 1), 380, (0, 5, 2), size=6)
soft.matrix_basis = Matrix.Translation((0, 5, 2)) @ Vector((0, -1, -0.35)).normalized().to_track_quat("-Z", "Y").to_matrix().to_4x4()

world = bpy.data.worlds.new("world")
world.use_nodes = True
world.node_tree.nodes["Background"].inputs["Color"].default_value = srgb(SPEC["colors"]["background"])
scene.world = world

# --- Camera ----------------------------------------------------------------
cam_data = bpy.data.cameras.new("camera")
cam_data.sensor_fit = "HORIZONTAL"
cam_data.angle = SPEC["camera"]["hfov"]
cam_data.clip_start, cam_data.clip_end = 0.05, 80
cam_data.dof.use_dof = True
cam_data.dof.aperture_fstop = SPEC["camera"]["fstop"]
camera = link(bpy.data.objects.new("camera", cam_data))
scene.camera = camera


# --- Per-frame update (also runs for motion-blur subframes) ----------------
def update(scn, *_):
    t = (scn.frame_current + scn.frame_subframe) / FPS
    pp, lp = m.phone_pose(SPEC, t), m.laptop_pose(SPEC, t)
    phone.matrix_basis = pose_matrix(pp["position"], pp["rotation"])
    laptop.matrix_basis = pose_matrix(lp["position"], lp["rotation"])

    cam = m.camera_at(SPEC, t)
    b = m.look_basis(cam["pos"], cam["look"])
    camera.matrix_basis = Matrix((
        (b["x"][0], b["y"][0], b["z"][0], cam["pos"][0]),
        (b["x"][1], b["y"][1], b["z"][1], cam["pos"][1]),
        (b["x"][2], b["y"][2], b["z"][2], cam["pos"][2]),
        (0, 0, 0, 1)))
    cam_data.dof.focus_distance = cam["focus"]

    for i, obj in enumerate(floor):
        state = m.floor_string(SPEC, t, i)
        set_points(obj, state["points"])
        obj.data.materials[0].node_tree.nodes["glow"].inputs["Strength"].default_value = state["level"] * 3.2

    # Hero endpoints from the same local points as three.js, in three.js axes.
    phone_m = pose_matrix(pp["position"], pp["rotation"])
    hinge_m = pose_matrix(lp["position"], lp["rotation"]) @ hinge.matrix_basis
    p0 = list(phone_m @ Vector(m.phone_launch_local(SPEC)))
    p1 = list(hinge_m @ Vector(m.tile_local(SPEC)))
    hero_state = m.hero_state(SPEC, t)
    glow = 1.6 + (2.2 * math.exp(-3 * hero_state["since"]) if hero_state["since"] >= 0 else 0)
    hero_mat.node_tree.nodes["glow"].inputs["Strength"].default_value = glow
    set_points(hero, [m.hero_point(SPEC, t, p0, p1, k / 120) for k in range(121)])

    at = m.hero_point(SPEC, t, p0, p1, hero_state["travel"])
    bead.location = at
    bead.hide_render = not (0 < hero_state["travel"] < 1)
    size = m.lerp(SPEC["photo"]["size"], L["tile"]["w"] * sw, hero_state["travel"])
    q = phone_m.to_quaternion().slerp(hinge_m.to_quaternion(), hero_state["travel"])
    card.matrix_basis = Matrix.Translation(at) @ q.to_matrix().to_4x4() @ Matrix.Diagonal((size, size, 1, 1))
    card_mat.node_tree.nodes["opacity"].inputs[1].default_value = hero_state["cardOpacity"]
    card.hide_render = hero_state["cardOpacity"] < 0.001
    laptop_screen_mat.node_tree.nodes["swap"].inputs["Factor"].default_value = hero_state["arrived"]


bpy.app.handlers.frame_change_pre.clear()
bpy.app.handlers.frame_change_pre.append(update)

# --- Render settings -------------------------------------------------------
fmt = SPEC["formats"][FORMAT]
r = scene.render
r.resolution_x, r.resolution_y, r.resolution_percentage = fmt["width"], fmt["height"], 100
r.fps = FPS
r.use_lock_interface = True
r.image_settings.file_format = "PNG"
r.image_settings.color_mode = "RGB"
for view in ("Khronos PBR Neutral", "Standard"):
    try:
        scene.view_settings.view_transform = view
        break
    except TypeError:
        continue
scene.view_settings.look = "None"

if ENGINE == "CYCLES":
    r.engine = "CYCLES"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "OPTIX"
    prefs.get_devices()
    for d in prefs.devices:
        d.use = d.type == "OPTIX"
    scene.cycles.device = "GPU"
    scene.cycles.samples = SAMPLES
    scene.cycles.use_adaptive_sampling = True
    scene.cycles.use_denoising = True
    scene.cycles.denoiser = "OPTIX"
    scene.cycles.max_bounces = 6
    scene.cycles.transparent_max_bounces = 8
    r.use_motion_blur = arg("--motion-blur", "1") == "1"
    r.motion_blur_shutter = 0.5
else:
    r.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = SAMPLES

# Bloom through the compositor, matching three.js' UnrealBloomPass role.
try:
    tree = bpy.data.node_groups.new("bloom", "CompositorNodeTree")
    tree.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    layers = tree.nodes.new("CompositorNodeRLayers")
    glare = tree.nodes.new("CompositorNodeGlare")
    glare.inputs["Type"].default_value = "Bloom"
    glare.inputs["Quality"].default_value = "High"
    glare.inputs["Threshold"].default_value = 0.72
    glare.inputs["Strength"].default_value = 1.0
    glare.inputs["Size"].default_value = 0.7
    output = tree.nodes.new("NodeGroupOutput")
    tree.links.new(layers.outputs["Image"], glare.inputs["Image"])
    tree.links.new(glare.outputs["Image"], output.inputs[0])
    scene.compositing_node_group = tree
    r.use_compositing = True
except Exception as error:  # report rather than silently render without bloom
    print("BLOOM SETUP FAILED:", error)

# --- Render ----------------------------------------------------------------
target = os.path.join(OUT, "blender", FORMAT)
os.makedirs(target, exist_ok=True)
total = round(SPEC["duration"] * FPS)
if FORMAT == "still":
    frames = [round(fmt["time"] * FPS)]
elif arg("--frames"):
    a, _, b = arg("--frames").partition("-")
    frames = list(range(int(a), int(b or a) + 1))
else:
    frames = list(range(total))

started = time.time()
for n in frames:
    scene.frame_set(n)
    r.filepath = os.path.join(target, "still.png" if FORMAT == "still" else f"{n:04d}.png")
    bpy.ops.render.render(write_still=True)
    print(f"FRAME {n} {time.time() - started:.1f}s", flush=True)
seconds = time.time() - started
timing = {"frames": len(frames), "seconds": seconds, "perFrame": seconds / len(frames), "engine": ENGINE, "samples": SAMPLES}
json.dump(timing, open(os.path.join(target, "timing.json" if not arg("--frames") else f"timing-{arg('--frames')}.json"), "w"), indent=2)
print("DONE", json.dumps(timing))
