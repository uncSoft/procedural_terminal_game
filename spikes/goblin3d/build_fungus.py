"""Spike: the Humongous Fungus rigged, animated and rendered in Blender, the way build_thornmother.py did the
Thornmother, from the front.

Reads the model inflate_fungus.py wrote (humongous_fungus/fungus_mesh.json). Runs headless:

    B=/Applications/Blender.app/Contents/MacOS/Blender
    $B -b --factory-startup --python spikes/goblin3d/build_fungus.py -- build   # humongous_fungus/humongous_fungus.glb + .blend
    $B -b spikes/goblin3d/humongous_fungus/humongous_fungus.blend --python spikes/goblin3d/build_fungus.py -- frames
    $B -b spikes/goblin3d/humongous_fungus/humongous_fungus.blend --python spikes/goblin3d/build_fungus.py -- test Attack 0 5 8

Four clips at 24 fps, all framed alike so its skirt stays on the same spot: Entrance (once; ends on Idle's first pose),
Idle (loops), Windup (loops: its tell, held) and Attack (once; from Idle's first pose back to it). "frames" renders
them from the front into humongous_fungus/frames_hd/<clip>/0/<frame>.png, 256 pixels a side, toon-shaded in its
sprite's colours, for reduce.py to shrink.

Its tell has its cap glow white. A bone with nothing on it ("glow") lights the cap, so the glow is keyed with the rest
of each clip: its x scale spreads white over the cap's lit side, and its z scale plain cyan (its shadow going first),
each from its crown down (1: none; 1.66: all of it); its y scale lets the white over the shadow side too, for a flash
(2: all of it). The .glb doesn't carry the glow.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bmesh
import bpy

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import build_king as kit  # noqa: E402
from build_king import P, aim, animate, build_model, build_rig, eased, linear, toon  # noqa: E402
from build_mouse import blend  # noqa: E402

TAG = kit.TAG = "humongous_fungus"  # the King's helpers name and find what they make by it
kit.GROUND = 23.7  # its skirt's front comes down below its foot, seen from a little above: the floor is under that
OUT = HERE / "humongous_fungus"
SCENE = "HumongousFungus"
SPAN, ELEVATION = 48, 12  # as every boss before it was framed
MESH = json.loads((OUT / "fungus_mesh.json").read_text())
CYAN, WHITE = "#2ce8f5", "#ffffff"
PUFFS = sorted(int(name.split("_")[1]) for name in MESH["bones"] if name.startswith("puff_"))
THREADS = sorted(name for name in MESH["bones"] if name.startswith("thread_"))


# -- poses ------------------------------------------------------------------------------------------------------------
# As in build_king.py: turns in degrees about the rig's axes (x to the viewer's right, y away, z up) and nudges in
# pixels; but its scales are given axis by axis (T), since it squashes and swells across the picture and up it without
# coming any nearer: for a bone standing up, sx is across, sy up and sz toward you. Its cap takes no scale from its
# stalk (or every breath would stretch it): fit() gives it the root's squash.

def T(rx=0.0, ry=0.0, rz=0.0, x=0.0, y=0.0, z=0.0, sx=1.0, sy=1.0, sz=1.0) -> tuple:
    return (rx, ry, rz), (x, y, z), (sx, sy, sz)


HIDDEN = T(sx=0.02, sy=0.02, sz=0.02)


def eyes(opened: float) -> dict:
    """1 open, as drawn; less narrows them to a glare, about their middles; 0 shut."""
    o = max(opened, 0.05)
    return {"eye_l": T(sy=o), "eye_r": T(sy=o)}


def gape(opened: float) -> dict:
    """0 shut (the frown it was drawn with), 1 wide open."""
    if opened < 0.03:
        return {"gape": HIDDEN}
    return {"gape": T(sx=0.55 + 0.45 * min(opened, 1.0), sy=opened)}


def glow(white: float, cyan: float | None = None, flash: float = 0.0) -> dict:
    """How far white has spread down the lit side of the cap from its crown (0 none, 0.66 all of it), plain cyan
    ahead of it (its shadow gone), and how far the white goes over the shadow side too (1: all of it)."""
    cyan = min(white + 0.3, 1.0) if cyan is None else cyan
    return {"glow": T(sx=1 + white, sy=1 + flash, sz=1 + cyan)}


def threads(out: float) -> dict:
    """Its threads pulled out from its stalk to the floor, taut (1), or drawn back into it (0)."""
    if out < 0.03:
        return {name: HIDDEN for name in THREADS}
    return {name: T(sy=out) for name in THREADS}


def cloud(n: int, at: tuple | None = None, size: float = 0.0) -> dict:
    """Cloud n carried to `at` (x, y down, depth: in pixels, as the model stands) and grown to `size` (0 hides it)."""
    if at is None or size < 0.03:
        return {f"puff_{n}": HIDDEN}
    hx, hy, hd = MESH["bones"][f"puff_{n}"]["head"]
    x, y, d = at
    return {f"puff_{n}": T(x=x - hx, y=-(d - hd), z=-(y - hy), sx=size, sy=size, sz=size)}


def billow(n: int, f: float, start: float, end: float, frm: tuple, to: tuple, top: float, mid: tuple | None = None,
           depth: float = 1.0) -> dict:
    """Cloud n puffed out at frame `start` from `frm` (x, y) and drifting to `to` by frame `end`, fast at first and
    slowing, curving through `mid` when it's given; growing to `top` at once, and dwindling away quickly at the end (a
    cloud shrunk small is only a speck)."""
    if not start < f < end:
        return cloud(n)
    s = (f - start) / (end - start)
    u = 1 - (1 - s) ** 2
    mid = mid or ((frm[0] + to[0]) / 2, (frm[1] + to[1]) / 2)
    x, y = ((1 - u) ** 2 * a + 2 * u * (1 - u) * b + u * u * c for a, b, c in zip(frm, mid, to))
    size = top * min(s / 0.2, 1.0) ** 0.5 * (1 - max((s - 0.72) / 0.28, 0.0) ** 2)
    return cloud(n, (x, y, depth), size)


def mirror(p: tuple) -> tuple:
    return (24 - p[0], *p[1:])


def still() -> dict:
    """Everything only out now and then, put away: its clouds, its threads, its open mouth and its glow."""
    return {**{f"puff_{n}": HIDDEN for n in PUFFS}, **threads(0.0), **gape(0.0), **glow(0.0, 0.0)}


def fit(pose: dict) -> dict:
    """The cap squashed with the root (it takes no scale from its parents)."""
    rot, nudge, (sx, sy, sz) = pose.get("cap", P())
    _, _, (across, up, _) = pose.get("root", P())
    return {**pose, "cap": (rot, nudge, (sx * across, sy * up, sz))}


def whip(t: float, keys: list) -> float:
    """A value running straight between (time, value) keys, without easing: for things brought down hard."""
    if t <= keys[0][0]:
        return keys[0][1]
    for (t0, v0), (t1, v1) in zip(keys, keys[1:]):
        if t <= t1:
            return v0 + (v1 - v0) * (t - t0) / (t1 - t0)
    return keys[-1][1]


def idle(t: float) -> dict:
    """It breathes, slowly: its cap sinks as it breathes out, spreading a little, and rises again as it breathes in,
    as in its sprite's two frames. Its face keeps still on its stalk: moved by less than a pixel, small eyes and a
    frown change shape from frame to frame."""
    w = 2 * math.pi * t
    out = 0.5 - 0.5 * math.cos(w)  # 0 risen, as in its first frame; 1 sunk, as in its second
    return {
        **still(),
        "cap": T(z=-0.65 * out, sx=1 + 0.035 * out, sy=1 - 0.025 * out),
        **eyes(1.0),
    }


REST = idle(0.0)
ENTRANCE, WINDUP, ATTACK = 72, 10, 20


def entrance(t: float) -> dict:
    """The Humongous Fungus arrives. 0-10: it drops from the roof, stretched by its fall. 10: its skirt hits the floor
    and it squashes down flat, its cap wobbling after it, spores puffed out either side. 10-22: it wobbles still.
    22-36: a long, slow breath in: its cap swells and glows brighter, it rises, its eyes close. 40-56: it breathes out,
    mouth wide: its spores billow out from under its cap in clouds, either side, and drift up and away. 56-70: it
    settles into its Idle."""
    f = t * ENTRANCE

    def k(*keys):
        return eased(f, list(keys))

    fall = 46 * (1 - (f / 10) ** 2) if f < 10 else 0.0  # faster and faster, like a dropped thing
    height = k((0, 1.1), (9.6, 1.1), (10.6, 0.7), (13, 1.08), (16, 0.95), (19, 1.02), (22, 1.0))
    breath = k((22, 0), (34, 1), (40, 1), (52, 0))
    pose = {
        **still(),
        "root": T(z=fall, sx=1 / math.sqrt(height), sy=height),
        "stalk": T(sx=1 - 0.03 * breath, sy=1 + 0.1 * breath, sz=1 - 0.03 * breath),
        "cap": T(sx=k((9.6, 1.0), (11.2, 1.07), (14, 0.97), (17, 1.0)) + 0.1 * breath,
                 sy=k((9.6, 1.0), (11.2, 0.92), (14, 1.03), (17, 1.0)) + 0.1 * breath),
        **eyes(k((22, 1.0), (28, 0.32), (38, 0.32), (42, 1.1), (46, 1.0))),
        **gape(k((40, 0), (43, 1.0), (50, 1.0), (55, 0))),
        **glow(0.0, cyan=0.5 * k((26, 0), (34, 1), (40, 1), (46, 0))),
    }
    for n, (start, end, frm, to, top, mid) in enumerate([
            (10, 22, (3.8, 21.6), (-3.0, 18.8), 1.15, (-0.3, 20.4)),  # off the floor as it lands
            (41, 61, (1.5, 15.5), (-2.7, 5.5), 1.4, (-2.6, 14.0)),  # its breath, out from under its cap and up
            (42.5, 62, (2.5, 17.5), (-2.5, 10.0), 1.25, (-2.2, 17.5)),
            (44, 64, (1.0, 14.0), (0.0, 0.5), 1.3, (-3.0, 9.5))]):
        pose.update(billow(1 + n, f, start, end, frm, to, top, mid))
        late = 0.0 if n == 0 else 1.0  # the right side a beat behind the left
        pose.update(billow(5 + n, f, start + late, end + late, mirror(frm), mirror(to), top, mid and mirror(mid)))
    return blend(pose, REST, k((62, 0), (70, 1)))


def raised(q: float = 0.0) -> dict:
    """Its tell: its cap swollen and glowing white, risen up on its stalk, its skirt gripping the floor, eyes narrowed,
    and the threads it has grown through the bed pulled tight out either side. q (-1 to 1) pulses it."""
    return {
        **still(),
        "root": T(x=0.1 * q),
        "stalk": T(sx=0.96, sy=1.12 + 0.012 * q, sz=0.96),
        "cap": T(sx=1.13 + 0.012 * q, sy=1.12 + 0.015 * q),
        "base": T(sx=1.04, sy=0.94),
        **eyes(0.55),
        **glow(0.6 + 0.1 * q, cyan=1.0),
        **threads(1.0 + 0.03 * q),
    }


def windup(t: float) -> dict:
    """The tell, held, pulsing."""
    return raised(math.sin(2 * math.pi * t))


def attack(t: float) -> dict:
    """0-4: it swells and rises, glowing, its threads pulled taut (Windup's pose). 4-5.6: up higher still, white.
    5.6-8: it brings its cap down hard, its stalk crushed under it. 8: the cap slams down, flattened wide, white, and
    the spores burst out from under it along the floor either side. 8-11: it holds it there, squashed. 11-16: it rises
    again, the glow going out of it and its threads let go, back in Idle's first pose by 19."""
    f = t * ATTACK

    def k(*keys):
        return eased(f, list(keys))

    def slam(*keys):  # risen by 5.6, then brought down hard
        return whip(f, list(keys)) if 5.6 <= f <= 8 else k(*keys)

    stalk = slam((0, 1.0), (4, 1.12), (5.6, 1.26), (8, 0.45), (9.2, 0.52), (10.5, 0.47), (12.5, 0.66), (15.5, 1.03),
                 (17, 1.0))
    wide = 1 + 0.5 * (1 - stalk) if stalk < 1 else 1 - 0.3 * (stalk - 1)
    white = slam((0, 0.0), (4, 0.6), (5.6, 0.68), (8, 1.0), (10, 1.0), (13, 0.45), (16, 0.0))
    pose = {
        **still(),
        "root": T(x=0.1 * math.sin(2 * math.pi * f / 2.5) * k((3, 0), (4, 1), (5.4, 1), (5.8, 0))),
        "stalk": T(sx=wide, sy=stalk, sz=wide),
        "cap": T(sx=slam((0, 1.0), (4, 1.13), (5.6, 1.16), (8, 1.32), (9.2, 1.24), (10.5, 1.29), (13, 1.08),
                         (16, 1.0)),
                 sy=slam((0, 1.0), (4, 1.12), (5.6, 1.2), (8, 0.76), (9.2, 0.85), (10.5, 0.8), (13, 0.99),
                         (16, 1.0))),
        "base": T(sx=k((0, 1), (4, 1.04), (7.5, 1.04), (8.5, 1.1), (11, 1.02), (14, 1.0)),
                  sy=k((0, 1), (4, 0.94), (7.5, 0.94), (8.5, 0.86), (11, 0.97), (14, 1.0))),
        **eyes(k((0, 1.0), (3, 0.55), (7, 0.5), (8, 0.25), (11, 0.3), (14, 1.0))),
        **gape(k((5.5, 0), (7.5, 0.9), (10.5, 1.0), (13.5, 0))),
        **glow(white, cyan=min(1.0, 2 * white), flash=k((7, 0), (8, 1), (9.5, 1), (11.5, 0))),
        **threads(k((0, 0.0), (2.5, 1.0), (8.2, 1.0), (11, 0.0))),
    }
    for n, (start, end, frm, to, top, mid) in enumerate([
            (7.0, 15, (3.0, 20.6), (-3.0, 17.6), 1.15, (-1.5, 19.8)),  # the burst, rolling out along the floor
            (7.3, 14, (4.2, 21.4), (-1.5, 20.4), 0.95, None),
            (7.9, 16, (2.0, 19.0), (-1.5, 10.5), 0.85, (-1.0, 15.5))]):
        pose.update(billow(1 + n, f, start, end, frm, to, top, mid))
        pose.update(billow(5 + n, f, start, end, mirror(frm), mirror(to), top, mid and mirror(mid)))
    return blend(pose, REST, max(k((0, 1), (1, 0)), k((15, 0), (19, 1))))


CLIPS = {"Entrance": (lambda t: fit(entrance(t)), ENTRANCE, False), "Idle": (lambda t: fit(idle(t)), 24, True),
         "Windup": (lambda t: fit(windup(t)), WINDUP, True), "Attack": (lambda t: fit(attack(t)), ATTACK, False)}


# -- the glow -----------------------------------------------------------------------------------------------------

def driven(socket, rig, channel: str, expression: str) -> None:
    """A node's input worked out from the "glow" bone's scale on one axis (s), by a simple expression: Blender works
    those out itself, without running any Python, so they work in a file opened without its scripts allowed."""
    driver = socket.driver_add("default_value").driver
    driver.type = "SCRIPTED"
    var = driver.variables.new()
    var.name, var.type = "s", "TRANSFORMS"
    var.targets[0].id = rig
    var.targets[0].bone_target = "glow"
    var.targets[0].transform_type = channel
    var.targets[0].transform_space = "LOCAL_SPACE"
    driver.expression = expression


def glow_material(rig) -> None:
    """The cap's cyan, lit by the "glow" bone: wherever it faces up more than one threshold it's drawn plain cyan (its
    shadow gone), and more than another, white where the light falls on it, so it keeps its shape: the glow fills the
    cap from its crown down. A third threshold lets the white over the shadow side too, for a flash."""
    mat = bpy.data.materials[f"{TAG} {CYAN}"]
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    shaded = nodes["toon"]
    shaded.name = "toon_shaded"
    normal = nodes.new("ShaderNodeNewGeometry")
    to_camera = nodes.new("ShaderNodeVectorTransform")
    to_camera.vector_type, to_camera.convert_from, to_camera.convert_to = "NORMAL", "WORLD", "CAMERA"
    links.new(normal.outputs["Normal"], to_camera.inputs["Vector"])

    def dot(towards):
        node = nodes.new("ShaderNodeVectorMath")
        node.operation = "DOT_PRODUCT"
        node.inputs[1].default_value = towards
        links.new(to_camera.outputs["Vector"], node.inputs[0])
        return node.outputs["Value"]

    def over(value, channel, expression):
        node = nodes.new("ShaderNodeMath")
        node.operation = "GREATER_THAN"
        links.new(value, node.inputs[0])
        driven(node.inputs[1], rig, channel, expression)
        return node.outputs[0]

    e = math.radians(ELEVATION)
    upward = dot((0.0, math.cos(e), -math.sin(e)))  # up, in the camera's space (y up, z ahead)
    cyan = over(upward, "SCALE_Z", "1.02 - 1.55 * (s - 1)")
    white = nodes.new("ShaderNodeMath")
    white.operation = "MULTIPLY"
    links.new(over(upward, "SCALE_X", "1.02 - 1.55 * (s - 1)"), white.inputs[0])
    links.new(over(dot(tuple(kit.LIGHT)), "SCALE_Y", f"{kit.LIT_FROM} - 1.3 * (s - 1)"), white.inputs[1])
    out = shaded
    for factor, colour in ((cyan, CYAN), (white.outputs[0], WHITE)):
        lit = nodes.new("ShaderNodeEmission")
        lit.inputs["Color"].default_value = (*linear(colour), 1.0)
        mix = nodes.new("ShaderNodeMixShader")
        links.new(factor, mix.inputs[0])
        links.new(out.outputs[0], mix.inputs[1])
        links.new(lit.outputs[0], mix.inputs[2])
        out = mix
    out.name = "toon"  # what toon() switches to


# -- building and rendering ---------------------------------------------------------------------------------------

def build() -> dict:
    scene = bpy.context.scene
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
    scene.name = SCENE
    scene.render.fps = kit.FPS
    scene.frame_start, scene.frame_end = 0, ENTRANCE
    body, n_verts, n_faces, palette = build_model(scene, MESH)
    # Where its colour changes (its dome to its dark lip, the lip to its gills), its shading doesn't blend across: the
    # glow goes by how far each bit of the cap faces up, and the lip's slope would tip the dome's bottom edge up.
    bm = bmesh.new()
    bm.from_mesh(body.data)
    for edge in bm.edges:
        faces = edge.link_faces
        if len(faces) == 2 and faces[0].material_index != faces[1].material_index:
            edge.smooth = False
    bm.to_mesh(body.data)
    bm.free()
    rig = build_rig(scene, MESH, body)
    # Its cap rides on its stalk without stretching with it: every breath would pull it tall.
    rig.data.bones["cap"].inherit_scale = "NONE"
    cam = bpy.data.objects.new(f"{TAG}_camera", bpy.data.cameras.new(f"{TAG}_camera"))
    cam.data.type = "ORTHO"
    scene.collection.objects.link(cam)
    scene.camera = cam
    aim(cam, yaw=0, elevation=ELEVATION, span=SPAN)
    sun = bpy.data.objects.new(f"{TAG}_sun", bpy.data.lights.new(f"{TAG}_sun", "SUN"))
    sun.data.energy = 3.0
    sun.rotation_euler = (math.radians(50), 0, math.radians(-30))
    scene.collection.objects.link(sun)
    actions = [animate(rig, name, pose, frames, loop) for name, (pose, frames, loop) in CLIPS.items()]
    rig.animation_data.action = actions[0]
    scene.frame_set(0)
    toon(False)
    glb = OUT / "humongous_fungus.glb"
    bpy.ops.export_scene.gltf(
        filepath=str(glb), export_format="GLB", use_active_scene=True,
        export_animations=True, export_animation_mode="ACTIONS", export_force_sampling=True,
        export_frame_range=False, export_anim_slide_to_zero=False, export_reset_pose_bones=True,
        export_skins=True, export_def_bones=False, export_yup=True, export_apply=False,
    )
    glow_material(rig)
    blend_file = OUT / "humongous_fungus.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_file))
    return {"verts": n_verts, "faces": n_faces, "colours": palette, "bones": len(rig.data.bones),
            "clips": [a.name for a in actions], "glb_bytes": glb.stat().st_size}


def setup(size: int = 256):
    """The scene, ready to render big toon frames: one sample (no blending), no filter, a clear background."""
    scene = bpy.data.scenes[SCENE]
    toon(True)
    render = scene.render
    render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = 1
    render.filter_size = 0.0
    render.resolution_x = render.resolution_y = size
    render.resolution_percentage = 100
    render.film_transparent = True
    render.image_settings.file_format = "PNG"
    render.image_settings.color_mode = "RGBA"
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    aim(scene.camera, yaw=0, elevation=ELEVATION, span=SPAN)
    return scene, scene.objects[f"{TAG}_rig"]


def render_frames(clips: tuple = tuple(CLIPS)) -> dict:
    scene, rig = setup()
    count = 0
    for clip in clips:
        frames = CLIPS[clip][1]
        rig.animation_data.action = bpy.data.actions[clip]
        scene.frame_start, scene.frame_end = 0, frames - 1  # the last pose is the next clip's first
        scene.render.filepath = str(OUT / "frames_hd" / clip / "0") + "/"
        bpy.ops.render.render(animation=True, scene=scene.name)
        count += frames
    toon(False)
    return {"frames": count, "folder": str(OUT / "frames_hd")}


def test_frames(clip: str, *frames: str) -> dict:
    """A few frames of a clip, to check the poses: humongous_fungus/test/<clip>_<frame>.png."""
    scene, rig = setup()
    rig.animation_data.action = bpy.data.actions[clip]
    paths = []
    for f in frames:
        scene.frame_set(int(f))
        scene.render.filepath = str(OUT / "test" / f"{clip}_{int(f):02d}.png")
        bpy.ops.render.render(write_still=True, scene=scene.name)
        paths.append(scene.render.filepath)
    return {"test": paths}


def main(task: str, *args) -> dict:
    if task == "build":
        return build()
    if task == "frames":
        return render_frames(tuple(args) or tuple(CLIPS))
    if task == "test":
        return test_frames(*args)
    raise SystemExit(f"unknown task {task!r}: build, frames or test")


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else ["build"]
    print("RESULT", json.dumps(main(*argv)))
