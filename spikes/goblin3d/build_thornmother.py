"""Spike: the Thornmother rigged, animated and rendered in Blender, the way build_abbot.py did the Drowned Abbot, from
the front.

Reads the model inflate_thornmother.py wrote (thornmother/thornmother_mesh.json). Runs headless:

    B=/Applications/Blender.app/Contents/MacOS/Blender
    $B -b --factory-startup --python spikes/goblin3d/build_thornmother.py -- build      # thornmother/thornmother.glb + .blend
    $B -b spikes/goblin3d/thornmother/thornmother.blend --python spikes/goblin3d/build_thornmother.py -- frames
    $B -b spikes/goblin3d/thornmother/thornmother.blend --python spikes/goblin3d/build_thornmother.py -- test Attack 0 5 8

Four clips at 24 fps, all framed alike so her roots stay on the same spot: Entrance (once; ends on Idle's first pose),
Idle (loops), Windup (loops: her tell, held) and Attack (once; from Idle's first pose back to it). "frames" renders
them from the front into thornmother/frames_hd/<clip>/0/<frame>.png, 256 pixels a side, toon-shaded in her sprite's
colours, for reduce.py to shrink.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Quaternion, Vector

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import build_king as kit  # noqa: E402
from build_king import P, aim, animate, build_model, build_rig, eased, toon  # noqa: E402
from build_mouse import blend  # noqa: E402

TAG = kit.TAG = "thornmother"  # the King's helpers name and find what they make by it
kit.GROUND = 23  # her roots reach a pixel lower than the King's boots: the floor is under them, framed the same
OUT = HERE / "thornmother"
SCENE = "Thornmother"
SPAN, ELEVATION = 48, 12  # as the King, King Mouse, Serpentis and the Abbot were framed
MESH = json.loads((OUT / "thornmother_mesh.json").read_text())


def angle(bone: str) -> float:
    """Which way a bone points in the picture, in degrees clockwise from straight up."""
    head, tail = MESH["bones"][bone]["head"], MESH["bones"][bone]["tail"]
    return math.degrees(math.atan2(tail[0] - head[0], head[1] - tail[1]))


PETALS = ["ll", "sl", "ml", "tl", "t", "tr", "mr", "sr", "lr"]  # left to right round her face
RANK = {name: min(PETALS.index(name), 8 - PETALS.index(name)) for name in PETALS}  # 4 at the top, 0 lowest
THETA = {name: angle(f"petal_{name}") for name in PETALS}


# -- poses ------------------------------------------------------------------------------------------------------------
# As in build_king.py: turns in degrees about the rig's axes (x to the viewer's right, y away, z up), nudges in pixels,
# a squash. A positive turn about y tips the top of a part toward the viewer's right (clockwise, as the viewer sees it).
# vine() and roots() turn her left side that way and mirror it for her right.

def bloom(fold: float = 0.0, spread: float = 0.0, each=None) -> dict:
    """Her petals, each folded forward about its base by `fold` degrees (135 closes them over her face in a bud; a
    negative fold flares them back) and spread out round her face in the picture by `spread` (negative gathers them
    in). each(name), when given, gives each petal its own (fold, spread)."""
    pose = {}
    for name in PETALS:
        f, s = each(name) if each else (fold, spread)
        theta = math.radians(THETA[name])
        out = 0 if name == "t" else (1 if theta > 0 else -1)
        turn = (Quaternion((0, 1, 0), math.radians(out * s))
                @ Quaternion(Vector((math.cos(theta), 0, -math.sin(theta))), math.radians(f)))
        e = turn.to_euler("YXZ")  # animate() turns about y, then x, then z
        pose[f"petal_{name}"] = P(rx=math.degrees(e.x), ry=math.degrees(e.y), rz=math.degrees(e.z))
    return pose


def vine(side: str, shoulder: float = 0.0, elbow: float = 0.0, wrist: float = 0.0, stretch: float = 1.0) -> dict:
    """Her vine on the viewer's left ("l") or right ("r"). For the left one, positive turns clockwise: the upper arm
    (pointing out) up, the forearm and tip (pointing up and in) further in over her head; negative uncurls them out and
    down. The right one mirrors it. stretch lengthens the forearm and tip."""
    sign = 1 if side == "l" else -1
    return {f"arm_{side}": P(ry=sign * shoulder), f"forearm_{side}": P(ry=sign * elbow, sq=stretch, wide=1.0),
            f"hand_{side}": P(ry=sign * wrist, sq=stretch, wide=1.0)}


def vines(shoulder: float = 0.0, elbow: float = 0.0, wrist: float = 0.0, stretch: float = 1.0) -> dict:
    return {**vine("l", shoulder, elbow, wrist, stretch), **vine("r", shoulder, elbow, wrist, stretch)}


def roots(outer: float = 0.0, inner: float = 0.0, middle: float = 0.0) -> dict:
    """Her roots turned out from her by so many degrees, raising their tips off the floor (never in: that would put
    them through it)."""
    pose = {}
    for side, sign in (("l", 1), ("r", -1)):
        for kind, turn in (("o", outer), ("i", inner), ("m", middle)):
            pose[f"rt_{kind}_{side}"] = P(ry=sign * max(turn, 0.0))
    return pose


def mouth(opened: float) -> dict:
    """0 shut (the line she was drawn with), 1 wide open."""
    o = min(max(opened, 0.0), 1.2)
    return {"mouth": P(sq=0.55 + 0.45 * o, wide=1.0 + 0.08 * o)}


def bits(landing: float = 0.0, hit: float = 0.0) -> dict:
    return {"splash_l": P(size=max(landing, 0.02)), "splash_r": P(size=max(landing, 0.02)),
            "burst": P(size=max(hit, 0.02))}


def whip(t: float, keys: list) -> float:
    """A value running straight between (time, value) keys, without easing: for things swung hard."""
    if t <= keys[0][0]:
        return keys[0][1]
    for (t0, v0), (t1, v1) in zip(keys, keys[1:]):
        if t <= t1:
            return v0 + (v1 - v0) * (t - t0) / (t1 - t0)
    return keys[-1][1]


def idle(t: float) -> dict:
    """She sinks a pixel on her roots and rises again, as in her two frames; her bloom breathes and her vines sway."""
    w = 2 * math.pi * t
    bob = 0.5 - 0.5 * math.cos(w)  # 0 up, as in her first frame; 1 sunk, as in her second
    return {
        "body": P(sq=1 - 0.085 * bob, wide=1 + 0.01 * bob, ry=0.6 * math.sin(w)),
        "head": P(rx=2 * math.sin(w - 0.8), ry=-1.5 * math.sin(w - 1.0)),
        **bloom(fold=3 * math.sin(w - 1.2), spread=2.5 * math.sin(w - 1.2)),
        **vine("l", 3 * math.sin(w - 1.4), -4 * math.sin(w - 1.9), -5 * math.sin(w - 2.4)),
        **vine("r", 3 * math.sin(w - 1.6), -4 * math.sin(w - 2.1), -5 * math.sin(w - 2.6)),
        **mouth(0.0),
        **bits(),
    }


REST = idle(0.0)
ENTRANCE, WINDUP, ATTACK = 72, 10, 20
LASH = 1.35  # how far her vine stretches when it cracks
BUD = 10  # how far her petals cup forward when they're gathered up in a bud


def entrance(t: float) -> dict:
    """The Thornmother arrives. 0-10: she drops from the roof, her petals gathered up in a bud, her roots flung out round her, her
    vines streaming up. 10: her roots slam into the floor and she squashes down on them, throwing up leaves. 10-22: she
    crouches. 22-36: she straightens and her bud bursts open, petal by petal from the top, round her face. 36-50: she
    shows off: bloom flared, mouth wide, vines lashing the air. 50-62: settles into her Idle."""
    f = t * ENTRANCE

    def k(*keys):
        return eased(f, list(keys))

    fall = 46 * (1 - (f / 10) ** 2) if f < 10 else 0.0  # faster and faster, like a dropped thing
    squash = k((0, 1.08), (9.5, 1.08), (10.5, 0.8), (13, 0.94), (17, 1.0))
    crouch = k((10, 0), (12, 1), (22, 1), (32, 0))
    show = k((34, 0), (38, 1), (48, 1), (56, 0))
    lash = math.sin(2 * math.pi * (f - 38) / 6) * k((37, 0), (39, 1), (47, 1), (50, 0))
    flung = k((0, 1), (9.5, 1), (10.2, 0))

    def petal(name):  # gathered up over her face in a bud, which opens from the top petals down
        shut = 1 - k((22 + 1.5 * (4 - RANK[name]), 0), (30 + 1.5 * (4 - RANK[name]), 1))
        gather = abs(THETA[name]) + (10 if name != "t" else 0)  # a little past upright, so they meet in a point
        return BUD * shut - 18 * show, -gather * shut + 7 * show

    pose = {
        "root": P(z=fall),
        "body": P(sq=squash * (1 - 0.05 * crouch) + 0.05 * show, wide=(1 / math.sqrt(squash)) * (1 + 0.03 * crouch),
                  rx=5 * crouch),
        "head": P(rx=k((0, -6), (9, -6), (11, 8), (13, 10), (22, 8), (32, 0), (36, -10), (48, -10), (56, 0))),
        **bloom(each=petal),
        **vines(k((0, 55), (9, 55), (11, -10), (14, -6), (22, -6), (32, 8), (48, 8), (56, 0)),
                k((0, -50), (9, -50), (11, 25), (22, 25), (32, -63), (48, -63), (56, 0)) - 20 * lash,
                k((0, -20), (9, -20), (11, 20), (22, 20), (32, 40), (48, 40), (56, 0)) - 30 * lash,
                k((0, 1.0), (22, 1.0), (32, 1.6), (48, 1.6), (56, 1.0))),
        **roots(45 * flung, 30 * flung, 25 * flung),
        **mouth(k((33, 0), (37, 1.1), (48, 1.0), (54, 0))),
        **bits(landing=whip(f, [(10, 0), (10.5, 0.7), (13, 1.0), (14, 1.1)]) if f < 14.5 else 0.0),
    }
    return blend(pose, REST, k((58, 0), (64, 1)))


def COCKED(q: float = 0.0) -> tuple:  # noqa: N802
    """A vine drawn back to lash: rising up and out beside her bloom, longer, its tip curled back in."""
    return 8 + 2 * q, -63 + 4 * q, 40 - 4 * q, 1.6


def raised(q: float = 0.0) -> dict:
    """Her tell: every root drawn taut, so she rises on them; her vines drawn up and back over her shoulders to lash;
    her bloom flared, her mouth open. q (-1 to 1) makes it quiver."""
    return {
        "body": P(sq=1.07, wide=0.97, z=0.7, x=0.12 * q),
        "head": P(rx=-6 + q),
        **bloom(fold=-15, spread=8 + 1.5 * q),
        **vine("l", *COCKED(q)),
        **vine("r", *COCKED(-q)),
        **mouth(0.85 + 0.15 * q),
        **bits(),
    }


def windup(t: float) -> dict:
    """The tell, held, shivering with it, twice a loop."""
    return raised(math.sin(4 * math.pi * t))


def attack(t: float) -> dict:
    """0-4: draws herself up (Windup's pose). 4-5.5: draws her vine on the viewer's right back further over her head.
    5.5-8: lashes it out to the viewer's right, uncurling and stretching. 8: its tip cracks, out level with her middle,
    throwing off shards. 8-11: holds it there. 11-15: reels it in, back to Idle's first pose by 18."""
    f = t * ATTACK

    def k(*keys):
        return eased(f, list(keys))

    up = k((0, 0), (4, 1), (5.5, 1), (8, 0))
    strike = k((5.5, 0), (8, 1), (11, 1), (15, 0))

    def lashed(*keys):  # drawn back by 5.5, then thrown hard
        return whip(f, list(keys)) if 5.5 <= f <= 8 else k(*keys)

    held = raised(0.0)
    pose = blend(REST, held, up)
    pose.update({
        "body": P(sq=1 + 0.07 * up - 0.03 * strike, wide=1 - 0.03 * up, z=0.7 * up, ry=7 * strike),  # her face kept nearly level
        "head": P(rx=-6 * up + 4 * strike, ry=-4 * strike),
        **bloom(fold=-15 * max(up, strike), spread=8 * max(up, strike)),
        **vine("l", 8 * up + 15 * strike, -63 * up - 20 * strike, 40 * up + 20 * strike, 1 + 0.6 * up + 0.3 * strike),
        **vine("r", lashed((0, 0), (4, 8), (5.5, 25), (7, 5), (8, 5), (11, 5), (15, 0)),
               lashed((0, 0), (4, -63), (5.5, -25), (7, -95), (8, -115), (11, -115), (15, 0)),
               lashed((0, 0), (4, 40), (5.5, 60), (7, -20), (8, -27), (11, -27), (15, 0)),
               lashed((0, 1.0), (4, 1.6), (5.5, 1.5), (7, 1.5), (8, LASH), (11, LASH), (15, 1.0))),
        **mouth(0.85 * up + k((6, 0), (8, 1.1), (11, 1.0), (14, 0))),
        **bits(hit=k((8, 0), (8.6, 0.75), (12, 1.35)) if f < 12.5 else 0.0),
    })
    return blend(pose, REST, max(k((0, 1), (1, 0)), k((14, 0), (18, 1))))


CLIPS = {"Entrance": (entrance, ENTRANCE, False), "Idle": (idle, 24, True), "Windup": (windup, WINDUP, True),
         "Attack": (attack, ATTACK, False)}


# -- building and rendering ---------------------------------------------------------------------------------------

def build() -> dict:
    scene = bpy.context.scene
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
    scene.name = SCENE
    scene.render.fps = kit.FPS
    scene.frame_start, scene.frame_end = 0, ENTRANCE
    body, n_verts, n_faces, palette = build_model(scene, MESH)
    rig = build_rig(scene, MESH, body)
    # She sinks by squashing her body; her head and vines ride on it without squashing, and her vines' tips keep their
    # own stretch when the forearm stretches.
    for bone in ("head", "arm_l", "arm_r", "hand_l", "hand_r"):
        rig.data.bones[bone].inherit_scale = "NONE"
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
    glb = OUT / "thornmother.glb"
    bpy.ops.export_scene.gltf(
        filepath=str(glb), export_format="GLB", use_active_scene=True,
        export_animations=True, export_animation_mode="ACTIONS", export_force_sampling=True,
        export_frame_range=False, export_anim_slide_to_zero=False, export_reset_pose_bones=True,
        export_skins=True, export_def_bones=False, export_yup=True, export_apply=False,
    )
    blend_file = OUT / "thornmother.blend"
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
    """A few frames of a clip, to check the poses: thornmother/test/<clip>_<frame>.png."""
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
