# Shared Blender kit for the Saiph ad sets: real-scale devices, materials, the
# wave strings, a keyed camera, bloom and a headless render loop. Each set's
# script builds its scene from these pieces. Units are metres; scene objects use
# three.js-style axes (y up) under one root empty, as in ../../2026-10-render-test.
import json
import math
import os
import sys
import time

import bmesh
import bpy
from mathutils import Matrix, Quaternion, Vector

COLORS = {"background": "#04070c", "wave1": "#22d3ee", "wave2": "#67e8f9", "wave3": "#a78bfa", "star": "#e7edf4", "body": "#1a2230"}


def args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return lambda name, default=None: argv[argv.index(name) + 1] if name in argv else default


def srgb(hex_color, scale=1.0):
    def lin(c):
        c = int(c, 16) / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    h = hex_color.lstrip("#")
    return (lin(h[0:2]) * scale, lin(h[2:4]) * scale, lin(h[4:6]) * scale, 1.0)


def clamp(x, a=0.0, b=1.0):
    return min(b, max(a, x))


def smooth(x):
    x = clamp(x)
    return x * x * x * (x * (x * 6 - 15) + 10)


def lerp(a, b, u):
    return a + (b - a) * u


def euler(r):
    """three.js 'XYZ' Euler order: R = Rx * Ry * Rz."""
    return Matrix.Rotation(r[0], 4, "X") @ Matrix.Rotation(r[1], 4, "Y") @ Matrix.Rotation(r[2], 4, "Z")


def pose(position, rotation=(0, 0, 0)):
    return Matrix.Translation(Vector(position)) @ euler(rotation)


# --- Scene -----------------------------------------------------------------
class Kit:
    def __init__(self):
        for obj in list(bpy.data.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        self.scene = bpy.context.scene
        self.root = bpy.data.objects.new("three_space", None)
        self.root.rotation_euler = (math.pi / 2, 0, 0)
        self.scene.collection.objects.link(self.root)
        self.updates = []
        self.sequences = []
        world = bpy.data.worlds.new("world")
        world.use_nodes = True
        world.node_tree.nodes["Background"].inputs["Color"].default_value = srgb(COLORS["background"])
        self.scene.world = world

    def link(self, obj, parent=None):
        self.scene.collection.objects.link(obj)
        obj.parent = parent or self.root
        return obj

    def empty(self, name, parent=None):
        return self.link(bpy.data.objects.new(name, None), parent)

    # --- Materials ---------------------------------------------------------
    @staticmethod
    def material(name):
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        nodes.clear()
        return mat, nodes, mat.node_tree.links, nodes.new("ShaderNodeOutputMaterial")

    def principled(self, name, color, roughness=0.5, metallic=0.0, coat=0.0, **extra):
        mat, nodes, links, out = self.material(name)
        bsdf = nodes.new("ShaderNodeBsdfPrincipled")
        bsdf.inputs["Base Color"].default_value = color
        bsdf.inputs["Roughness"].default_value = roughness
        bsdf.inputs["Metallic"].default_value = metallic
        bsdf.inputs["Coat Weight"].default_value = coat
        for key, value in extra.items():
            bsdf.inputs[key].default_value = value
        links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
        return mat

    def body(self):
        return self.principled("body", srgb(COLORS["body"]), 0.32, 0.75, coat=0.5)

    def emission(self, name, color, strength):
        mat, nodes, links, out = self.material(name)
        emit = nodes.new("ShaderNodeEmission")
        emit.name = "glow"
        emit.inputs["Color"].default_value = color
        emit.inputs["Strength"].default_value = strength
        links.new(emit.outputs["Emission"], out.inputs["Surface"])
        return mat

    def screen(self, name, path, strength=1.0, glass=True):
        """Self-lit screen with a thin glossy glass layer. Node 'tex' holds the image;
        node 'opacity' fades it. A path ending in a folder plays that PNG sequence."""
        mat, nodes, links, out = self.material(name)
        tex = nodes.new("ShaderNodeTexImage")
        tex.name = "tex"
        tex.interpolation = "Cubic"
        if os.path.isdir(path):
            files = sorted(f for f in os.listdir(path) if f.endswith(".png"))
            tex.image = bpy.data.images.load(os.path.join(path, files[0]))
            self.sequences.append((tex.image, path))
        else:
            tex.image = bpy.data.images.load(path, check_existing=True)
        emit = nodes.new("ShaderNodeEmission")
        emit.inputs["Strength"].default_value = strength
        links.new(tex.outputs["Color"], emit.inputs["Color"])
        surface = emit.outputs["Emission"]
        if glass:
            gloss = nodes.new("ShaderNodeBsdfGlossy")
            gloss.inputs["Roughness"].default_value = 0.05
            fresnel = nodes.new("ShaderNodeLayerWeight")
            fresnel.inputs["Blend"].default_value = 0.1
            layer = nodes.new("ShaderNodeMixShader")
            links.new(fresnel.outputs["Fresnel"], layer.inputs["Fac"])
            links.new(surface, layer.inputs[1])
            links.new(gloss.outputs["BSDF"], layer.inputs[2])
            surface = layer.outputs["Shader"]
        fade = nodes.new("ShaderNodeMath")
        fade.name = "opacity"
        fade.operation = "MULTIPLY"
        fade.inputs[1].default_value = 1.0
        links.new(tex.outputs["Alpha"], fade.inputs[0])
        clear = nodes.new("ShaderNodeBsdfTransparent")
        mix = nodes.new("ShaderNodeMixShader")
        links.new(fade.outputs[0], mix.inputs["Fac"])
        links.new(clear.outputs["BSDF"], mix.inputs[1])
        links.new(surface, mix.inputs[2])
        links.new(mix.outputs["Shader"], out.inputs["Surface"])
        return mat

    def line(self, name, strength):
        """Emission along a string, cyan through light cyan to violet across its bounds."""
        mat, nodes, links, out = self.material(name)
        coords = nodes.new("ShaderNodeTexCoord")
        sep = nodes.new("ShaderNodeSeparateXYZ")
        links.new(coords.outputs["Generated"], sep.inputs["Vector"])
        ramp = nodes.new("ShaderNodeValToRGB")
        el = ramp.color_ramp.elements
        el[0].position, el[0].color = 0.0, srgb(COLORS["wave1"])
        el[1].position, el[1].color = 1.0, srgb(COLORS["wave3"])
        mid = el.new(0.45)
        mid.color = srgb(COLORS["wave2"])
        links.new(sep.outputs["X"], ramp.inputs["Fac"])
        emit = nodes.new("ShaderNodeEmission")
        emit.name = "glow"
        emit.inputs["Strength"].default_value = strength
        links.new(ramp.outputs["Color"], emit.inputs["Color"])
        links.new(emit.outputs["Emission"], out.inputs["Surface"])
        return mat

    # --- Geometry ----------------------------------------------------------
    def box(self, name, size, radius, material, parent=None, segments=5):
        mesh = bpy.data.meshes.new(name)
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1.0)
        for v in bm.verts:
            v.co = Vector((v.co.x * size[0], v.co.y * size[1], v.co.z * size[2]))
        bm.to_mesh(mesh)
        bm.free()
        mesh.materials.append(material)
        for poly in mesh.polygons:
            poly.use_smooth = True
        obj = bpy.data.objects.new(name, mesh)
        if radius > 0:
            bevel = obj.modifiers.new("round", "BEVEL")
            bevel.width = radius
            bevel.segments = segments
            bevel.limit_method = "NONE"
        return self.link(obj, parent)

    def plane(self, name, w, h, material, parent=None):
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata([(-w / 2, -h / 2, 0), (w / 2, -h / 2, 0), (w / 2, h / 2, 0), (-w / 2, h / 2, 0)], [], [(0, 1, 2, 3)])
        uv = mesh.uv_layers.new()
        for loop, co in zip(uv.data, [(0, 0), (1, 0), (1, 1), (0, 1)]):
            loop.uv = co
        mesh.materials.append(material)
        return self.link(bpy.data.objects.new(name, mesh), parent)

    def cylinder(self, name, radius, depth, material, parent=None, segments=48):
        mesh = bpy.data.meshes.new(name)
        bm = bmesh.new()
        bmesh.ops.create_cone(bm, cap_ends=True, segments=segments, radius1=radius, radius2=radius, depth=depth)
        bm.to_mesh(mesh)
        bm.free()
        mesh.materials.append(material)
        for poly in mesh.polygons:
            poly.use_smooth = True
        obj = bpy.data.objects.new(name, mesh)
        obj.modifiers.new("smooth", "WEIGHTED_NORMAL")
        return self.link(obj, parent)

    def curve(self, name, points, radius, material, parent=None):
        data = bpy.data.curves.new(name, "CURVE")
        data.dimensions = "3D"
        data.bevel_depth = radius
        data.bevel_resolution = 2
        data.use_fill_caps = True
        spline = data.splines.new("POLY")
        spline.points.add(len(points) - 1)
        data.materials.append(material)
        obj = self.link(bpy.data.objects.new(name, data), parent)
        set_points(obj, points)
        return obj

    # --- Devices (real-world size) ----------------------------------------
    def phone(self, name, screen_path=None, parent=None):
        """Phone centred on its origin, screen facing +z. 75 x 160 x 8 mm."""
        group = self.empty(name, parent)
        body = self.body()
        self.box(name + "_body", (0.075, 0.16, 0.008), 0.009, body, group)
        bump = self.box(name + "_camera", (0.05, 0.016, 0.002), 0.004, body, group)
        bump.location = (0, 0.058, -0.005)
        glass = self.principled(name + "_lens", srgb("#05070b"), 0.08, 0.2, coat=1.0)
        for i, x in enumerate((-0.012, 0.004)):
            lens = self.cylinder(f"{name}_lens{i}", 0.0045, 0.0015, glass, group)
            lens.matrix_basis = Matrix.Translation((x, 0.058, -0.0065)) @ Matrix.Rotation(math.pi / 2, 4, "X")
        if screen_path:
            self.plane(name + "_screen", 0.0715, 0.1565, self.screen(name + "_screen", screen_path), group).location = (0, 0, 0.0041)
        else:
            self.plane(name + "_screen", 0.0715, 0.1565, self.principled(name + "_off", srgb("#020304"), 0.06, coat=1.0), group).location = (0, 0, 0.0041)
        return group

    def laptop(self, name, screen_path, parent=None, open_angle=1.85):
        """Laptop with its base centred on the origin; returns (group, hinge, screen).
        Screen 288 x 180 mm (16:10); the lid's front face points +z when upright."""
        group = self.empty(name, parent)
        body = self.body()
        bw, bh, bd = 0.31, 0.015, 0.215
        self.box(name + "_base", (bw, bh, bd), 0.006, body, group).location = (0, bh / 2, 0)
        keys = self.principled(name + "_keys", srgb("#0b0f16"), 0.75)
        well = self.plane(name + "_well", bw * 0.88, bd * 0.42, keys, group)
        well.matrix_basis = Matrix.Translation((0, bh + 0.0004, -bd * 0.17)) @ Matrix.Rotation(-math.pi / 2, 4, "X")
        pad = self.plane(name + "_pad", bw * 0.36, bd * 0.3, self.principled(name + "_padm", srgb("#202938"), 0.35, 0.4), group)
        pad.matrix_basis = Matrix.Translation((0, bh + 0.0004, bd * 0.25)) @ Matrix.Rotation(-math.pi / 2, 4, "X")
        hinge = self.empty(name + "_hinge", group)
        hinge.matrix_basis = Matrix.Translation((0, bh, -bd / 2)) @ Matrix.Rotation(-(open_angle - math.pi / 2), 4, "X")
        lw, lh, lt = 0.31, 0.205, 0.006
        self.box(name + "_lid", (lw, lh, lt), 0.004, body, hinge).location = (0, lh / 2, lt / 2)
        screen = self.plane(name + "_screen", 0.288, 0.18, self.screen(name + "_screen", screen_path), hinge)
        screen.location = (0, lh / 2 + 0.006, lt + 0.0004)
        return group, hinge, screen

    def wave_wall(self, name, count, x_range, y_range, z, strength=3.0, parent=None, swell=0.9):
        """Horizontal light strings stacked on a back wall, drifting like the app's field.
        Returns an update(t, pluck) that moves them; pluck is (time, x, y) or None."""
        strings = []
        for i in range(count):
            strings.append(self.curve(f"{name}_{i:02d}", [[0, 0, 0]] * 121, 0.0012, self.line(f"{name}_{i:02d}", strength), parent))

        def update(t, pluck=None):
            for i, obj in enumerate(strings):
                depth = (i + 1) / (count + 1)
                y0 = lerp(y_range[0], y_range[1], depth)
                gap = (y_range[1] - y_range[0]) / (count + 1)
                level = 0.07 + 0.26 * math.sin(math.pi * depth) ** 2
                peak, pts = 0.0, []
                for k in range(121):
                    u = k / 120
                    x = lerp(x_range[0], x_range[1], u)
                    y = (y0 + math.sin(u * 2.6 * 1.6 + depth * 4.1 + 0.25 * t) * gap * swell
                         + math.sin(u * 6.3 * 1.6 - depth * 2.2 - 0.15 * t) * gap * 0.25 + 0.0006 * math.sin(u * 22 + i * 0.7 + t))
                    if pluck and t >= pluck[0]:
                        since = t - pluck[0]
                        d = math.hypot(x - pluck[1], y0 - pluck[2])
                        bump = math.exp(-(((d - 0.9 * since) / 0.12) ** 2)) * math.exp(-1.2 * since)
                        peak = max(peak, bump)
                        y += gap * 1.2 * bump * math.sin(30 * since + u * 20)
                    pts.append([x, y, z])
                set_points(obj, pts)
                obj.data.materials[0].node_tree.nodes["glow"].inputs["Strength"].default_value = level * strength * (1 + 2.5 * peak)
        return update

    def desk(self):
        """Walnut desk at y = 0 and a dark back wall with drifting light strings.
        Returns the strings' update(t, pluck)."""
        mat, nodes, links, out = self.material("desk")
        noise = nodes.new("ShaderNodeTexNoise")
        noise.inputs["Scale"].default_value = 3.0
        noise.inputs["Detail"].default_value = 8.0
        mapping = nodes.new("ShaderNodeMapping")
        mapping.inputs["Scale"].default_value = (1.0, 22.0, 1.0)
        coords = nodes.new("ShaderNodeTexCoord")
        links.new(coords.outputs["Object"], mapping.inputs["Vector"])
        links.new(mapping.outputs["Vector"], noise.inputs["Vector"])
        ramp = nodes.new("ShaderNodeValToRGB")
        ramp.color_ramp.elements[0].color = srgb("#1a120d")
        ramp.color_ramp.elements[1].color = srgb("#3a281c")
        links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
        bsdf = nodes.new("ShaderNodeBsdfPrincipled")
        bsdf.inputs["Roughness"].default_value = 0.42
        bsdf.inputs["Coat Weight"].default_value = 0.25
        links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
        links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
        top = self.plane("desk", 2.4, 1.4, mat)
        top.matrix_basis = Matrix.Translation((0, 0, -0.1)) @ Matrix.Rotation(-math.pi / 2, 4, "X")
        self.plane("wall", 4.0, 2.4, self.principled("wall", srgb("#070b12"), 0.9)).location = (0, 0.6, -0.78)
        return self.wave_wall("wave", 9, (-1.3, 1.3), (0.0, 1.05), -0.74, strength=2.2, swell=2.4)

    def keyboard(self, parent, top_y, centre_z, pitch=0.0185):
        """A backlit ANSI-style keyboard on a laptop base. Returns {label: (keycap, rest matrix)}."""
        rows = [
            [("`", 1)] + [(c, 1) for c in "1234567890-="] + [("Back", 2)],
            [("Tab", 1.5)] + [(c, 1) for c in "QWERTYUIOP[]"] + [("\\", 1.5)],
            [("Caps", 1.75)] + [(c, 1) for c in "ASDFGHJKL;'"] + [("Enter", 2.25)],
            [("Shift", 2.25)] + [(c, 1) for c in "ZXCVBNM,./"] + [("Shift ", 2.75)],
            [("Ctrl", 1.25), ("Fn", 1), ("", 1), ("Alt", 1), ("", 5.5), ("Alt ", 1), ("Ctrl ", 1.25), ("<", 1), ("v", 1), (">", 1)],
        ]
        cap = self.principled("keycap", srgb("#141a24"), 0.45, coat=0.2)
        legend = self.emission("legend", srgb("#cfefff"), 1.6)
        keys = {}
        gap = 0.0026
        for r, row in enumerate(rows):
            x = -7.5 * pitch
            z = centre_z + (r - 2) * pitch
            for label, width in row:
                w = width * pitch
                key = self.box(f"key_{r}_{label or 'blank'}_{x:.3f}", (w - gap, 0.0018, pitch - gap), 0.0011, cap, parent, segments=3)
                rest = Matrix.Translation((x + w / 2, top_y + 0.0009, z))
                key.matrix_basis = rest
                text = label.strip()
                if text:
                    data = bpy.data.curves.new(f"legend_{r}_{x:.3f}", "FONT")
                    data.body = text
                    data.size = 0.0046 if len(text) == 1 else 0.0032
                    data.align_x, data.align_y = "CENTER", "CENTER"
                    data.materials.append(legend)
                    glyph = self.link(bpy.data.objects.new(f"glyph_{r}_{x:.3f}", data), key)
                    glyph.matrix_basis = Matrix.Translation((0, 0.00095, 0)) @ Matrix.Rotation(-math.pi / 2, 4, "X")
                if label and label not in keys:
                    keys[label] = (key, rest)
                x += w
        return keys

    # --- Camera ------------------------------------------------------------
    def camera(self, hfov=0.62, fstop=2.0):
        data = bpy.data.cameras.new("camera")
        data.sensor_fit = "HORIZONTAL"
        data.angle = hfov
        data.clip_start, data.clip_end = 0.01, 40
        data.dof.use_dof = True
        data.dof.aperture_fstop = fstop
        cam = self.link(bpy.data.objects.new("camera", data))
        self.scene.camera = cam
        return cam

    def light(self, name, kind, color, energy, position, target=None, size=None):
        data = bpy.data.lights.new(name, kind)
        data.color = color[:3]
        data.energy = energy
        if size is not None and kind == "AREA":
            data.size = size
        obj = self.link(bpy.data.objects.new(name, data))
        obj.visible_camera = False  # light the scene; never appear as a glowing panel
        rot = Matrix.Identity(4)
        if target is not None:
            rot = (Vector(target) - Vector(position)).normalized().to_track_quat("-Z", "Y").to_matrix().to_4x4()
        obj.matrix_basis = Matrix.Translation(position) @ rot
        return obj

    # --- Rendering ---------------------------------------------------------
    def setup_render(self, width, height, fps, samples, motion_blur=True, bloom=(0.75, 0.8, 0.65)):
        r = self.scene.render
        # --scale 50 renders a quick draft at half size; finish.cjs scales it back up.
        r.resolution_x, r.resolution_y, r.resolution_percentage = width, height, int(args()("--scale", "100"))
        r.fps = fps
        r.use_lock_interface = True
        r.image_settings.file_format = "PNG"
        r.image_settings.color_mode = "RGB"
        for view in ("Khronos PBR Neutral", "Standard"):
            try:
                self.scene.view_settings.view_transform = view
                break
            except TypeError:
                continue
        r.engine = "CYCLES"
        prefs = bpy.context.preferences.addons["cycles"].preferences
        prefs.compute_device_type = "OPTIX"
        prefs.get_devices()
        for d in prefs.devices:
            d.use = d.type == "OPTIX"
        c = self.scene.cycles
        c.device = "GPU"
        c.samples = samples
        c.use_adaptive_sampling = True
        c.use_denoising = True
        c.denoiser = "OPTIX"
        c.max_bounces = 6
        c.transparent_max_bounces = 8
        r.use_motion_blur = motion_blur
        r.motion_blur_shutter = 0.5
        tree = bpy.data.node_groups.new("bloom", "CompositorNodeTree")
        tree.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
        layers = tree.nodes.new("CompositorNodeRLayers")
        glare = tree.nodes.new("CompositorNodeGlare")
        glare.inputs["Type"].default_value = "Bloom"
        glare.inputs["Quality"].default_value = "High"
        glare.inputs["Threshold"].default_value = bloom[0]
        glare.inputs["Strength"].default_value = bloom[1]
        glare.inputs["Size"].default_value = bloom[2]
        output = tree.nodes.new("NodeGroupOutput")
        tree.links.new(layers.outputs["Image"], glare.inputs["Image"])
        tree.links.new(glare.outputs["Image"], output.inputs[0])
        self.scene.compositing_node_group = tree
        r.use_compositing = True

    def on_frame(self, fn):
        self.updates.append(fn)

    def install(self, fps):
        kit = self

        def update(scn, *_):
            t = (scn.frame_current + scn.frame_subframe) / fps
            frame = scn.frame_current
            for image, folder in kit.sequences:
                path = os.path.join(folder, f"{frame:04d}.png")
                if os.path.exists(path) and image.filepath != path:
                    image.filepath = path
                    image.reload()
            for fn in kit.updates:
                fn(t)
        bpy.app.handlers.frame_change_pre.clear()
        bpy.app.handlers.frame_change_pre.append(update)

    def render(self, out_dir, frames, label):
        os.makedirs(out_dir, exist_ok=True)
        started = time.time()
        for n in frames:
            self.scene.frame_set(n)
            self.scene.render.filepath = os.path.join(out_dir, f"{label}.png" if label else f"{n:04d}.png")
            bpy.ops.render.render(write_still=True)
            print(f"FRAME {n} {time.time() - started:.1f}s", flush=True)
        seconds = time.time() - started
        info = {"frames": len(frames), "seconds": seconds, "perFrame": seconds / max(1, len(frames))}
        json.dump(info, open(os.path.join(out_dir, f"timing-{label or 'story'}-{frames[0]}.json"), "w"), indent=2)
        print("DONE", json.dumps(info))


def set_points(obj, points):
    for p, co in zip(obj.data.splines[0].points, points):
        p.co = (co[0], co[1], co[2], 1.0)


# --- Camera keys -------------------------------------------------------------
def catmull(p0, p1, p2, p3, u):
    u2, u3 = u * u, u * u * u
    return [0.5 * (2 * p1[i] + (-p0[i] + p2[i]) * u + (2 * p0[i] - 5 * p1[i] + 4 * p2[i] - p3[i]) * u2
                   + (-p0[i] + 3 * p1[i] - 3 * p2[i] + p3[i]) * u3) for i in range(len(p1))]


def camera_at(keys, t):
    """keys: [{t, pos, look}] in world (three.js axes). Holds briefly at each key."""
    i = 0
    while i < len(keys) - 2 and t > keys[i + 1]["t"]:
        i += 1
    k1, k2 = keys[i], keys[i + 1]
    k0, k3 = keys[max(0, i - 1)], keys[min(len(keys) - 1, i + 2)]
    u = smooth(clamp((t - k1["t"]) / (k2["t"] - k1["t"])) * 0.6 + 0.4 * clamp((t - k1["t"]) / (k2["t"] - k1["t"])))
    return catmull(k0["pos"], k1["pos"], k2["pos"], k3["pos"], u), catmull(k0["look"], k1["look"], k2["look"], k3["look"], u)


def glide(shots, t, pose, blend=0.6, hard=()):
    """Camera (pos, look) for shot lists of (start, end, ...): pose(shot, t) inside each shot,
    and an eased glide over `blend` seconds across every cut instead of a hard cut, except
    at the cut times listed in `hard`."""
    i = next((k for k, s in enumerate(shots) if s[0] <= t < s[1]), len(shots) - 1)
    a, b, h = shots[i][0], shots[i][1], blend / 2
    if i > 0 and t < a + h and a not in hard:
        frm, to, start = (shots[i - 1], a - h), (shots[i], a + h), a - h
    elif i < len(shots) - 1 and t >= b - h and b not in hard:
        frm, to, start = (shots[i], b - h), (shots[i + 1], b + h), b - h
    else:
        p, l = pose(shots[i], t)
        return Vector(p), Vector(l)
    (p0, l0), (p1, l1) = pose(*frm), pose(*to)
    u = smooth((t - start) / blend)
    return Vector(p0).lerp(Vector(p1), u), Vector(l0).lerp(Vector(l1), u)


def aim(cam, pos, look, roll=0.0):
    z = (Vector(pos) - Vector(look)).normalized()
    x = Vector((0, 1, 0)).cross(z).normalized()
    y = z.cross(x)
    m = Matrix(((x[0], y[0], z[0], pos[0]), (x[1], y[1], z[1], pos[1]), (x[2], y[2], z[2], pos[2]), (0, 0, 0, 1)))
    cam.matrix_basis = m @ Matrix.Rotation(roll, 4, "Z")
    cam.data.dof.focus_distance = (Vector(pos) - Vector(look)).length
