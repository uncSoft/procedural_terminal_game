"""Spike: Serpentis rigged, animated and rendered in Blender, the way build_mouse.py did King Mouse, from the front.

Reads the model inflate_serpentis.py wrote (serpentis/serpentis_mesh.json). Runs headless:

    B=/Applications/Blender.app/Contents/MacOS/Blender
    $B -b --factory-startup --python spikes/goblin3d/build_serpentis.py -- build      # serpentis/serpentis.glb + .blend
    $B -b spikes/goblin3d/serpentis/serpentis.blend --python spikes/goblin3d/build_serpentis.py -- frames
    $B -b spikes/goblin3d/serpentis/serpentis.blend --python spikes/goblin3d/build_serpentis.py -- test Attack 0 5 8

Four clips at 24 fps, all framed alike so her coils stay on the same spot: Entrance (once; ends on Idle's first
pose), Idle (loops), Windup (loops: how she holds herself while a strike is coming) and Attack (once; from Idle's first
pose back to it). "frames" renders them from the front into serpentis/frames_hd/<clip>/0/<frame>.png, 256 pixels a
side, toon-shaded in her sprite's colours, for reduce.py to shrink.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import build_king as kit  # noqa: E402
from build_king import P, aim, animate, build_model, build_rig, eased, toon  # noqa: E402
from build_mouse import blend  # noqa: E402

TAG = kit.TAG = "serpentis"  # the King's helpers name and find what they make by it
OUT = HERE / "serpentis"
SCENE = "Serpentis"
SPAN, ELEVATION = 48, 12  # as the King and King Mouse were framed
JAW_DROP, MOUTH = 2.2, 2.0  # how far her jaw drops wide open, and her mouth's height shut (its bone), in pixels


# -- poses ------------------------------------------------------------------------------------------------------------
# As in build_king.py: turns in degrees about the rig's axes (x to the viewer's right, y away, z up), nudges in pixels,
# a squash. A positive turn about y tips the top of a part toward the viewer's right: her body sways by it, her arms
# lift by it (her left arm, on the viewer's left, positive; her right negative), and her coils curl in by it (left
# positive, right negative). Her tongue hangs straight down until it's curled to a side. Her fangs' size runs from 0
# (folded away) to 1.

def mouth(opened: float) -> dict:
    """Her jaw dropped and her mouth stretched to match: 0 shut, 1 wide open."""
    drop = JAW_DROP * opened
    return {"jaw": P(z=-drop), "mouth": P(sq=(MOUTH + drop) / MOUTH, wide=1.0)}


def fangs(out: float) -> dict:
    return {"fang_l": P(size=max(out, 0.02)), "fang_r": P(size=max(out, 0.02))}


def tongue(side: float, flick: float = 0.0, out: float = 1.0) -> dict:
    """Her tongue curled to a side (1 to the viewer's right, as in her first frame; -1 to the left, as in her second;
    0 hanging straight), flicked by `flick` degrees, and drawn in to `out` of its length."""
    return {"tongue_1": P(ry=-15 * side + 0.5 * flick, size=out), "tongue_2": P(ry=-75 * side + flick),
            "tongue_3": P(ry=-60 * side + 1.5 * flick)}


def arms(raised: float = 0.0, spread: float = 0.0, left: float | None = None) -> dict:
    """Her arms: 0 out and up as in her first frame, 1 high beside her head as in her second; spread opens her
    hands. `left` raises her left arm (the viewer's left) apart from her right."""
    pose = {}
    for side, sign, r in (("l", 1, raised if left is None else left), ("r", -1, raised)):
        pose[f"arm_{side}"] = P(ry=sign * 14 * r)
        pose[f"forearm_{side}"] = P(ry=sign * 26 * r)
        pose[f"hand_{side}"] = P(ry=sign * (-18 * r + 12 * spread))
    return pose


def coils(curl: float = 0.0, tips: float = 0.0, right: float | None = None) -> dict:
    """Her tails curled in toward her (negative: out), and their tips curled further. `right` curls the viewer's
    right one apart from the left."""
    pose = {}
    for side, sign, c in (("l", 1, curl), ("r", -1, curl if right is None else right)):
        pose[f"tail_{side}_2"] = P(ry=sign * 0.3 * c)
        pose[f"tail_{side}_3"] = P(ry=sign * 0.5 * c)
        pose[f"tail_{side}_4"] = P(ry=sign * (c + tips))
    return pose


def neck(lean: float, s1: float, s2: float, s3: float, head: float = 0.0, stretch: float = 1.0) -> dict:
    """Her body swayed: each of its three stretches turned in the picture (degrees) and stretched, and her head turned
    back by `head` so she keeps her eyes on you."""
    return {"body_1": P(ry=lean + s1), "body_2": P(ry=s2, sq=stretch, wide=1.0),
            "body_3": P(ry=s3, sq=stretch, wide=1.0), "head": P(ry=head)}


def idle(t: float) -> dict:
    """Coiled and watching you: her body sways like a charmed snake's, her head kept level; her tongue swings from
    one side to the other and back, as in her two frames; her hands flex, her crown breathes, her tails' tips twitch."""
    w = 2 * math.pi * t
    side = math.tanh(2.5 * math.cos(w)) / math.tanh(2.5)
    pose = neck(0, 1.2 * math.sin(w), 2.5 * math.sin(w - 0.7), 3.0 * math.sin(w - 1.4),
                head=-5.0 * math.sin(w - 1.4), stretch=1 + 0.015 * math.sin(w - 0.4))
    pose["head"] = P(ry=pose["head"][0][1], rx=1.5 * math.sin(2 * w))
    return {
        **pose,
        "crown": P(wide=1 + 0.02 * (0.5 - 0.5 * math.cos(w))),
        **tongue(side),
        **arms(0.15 + 0.15 * math.sin(w - 0.9), spread=0.5 + 0.5 * math.sin(w - 1.6)),
        **coils(0, tips=6 * math.sin(w + 0.8)),
        **mouth(0), **fangs(0),
    }


REST = idle(0.0)
ENTRANCE, WINDUP, ATTACK = 72, 10, 20


def entrance(t: float) -> dict:
    """Serpentis arrives. 0-10: she drops from the roof of her lair, stretched long, her tails trailing up. 10: her
    coils hit the floor. 10-22: she slumps into them, her head low, glaring. 22-30: rears up tall. 30-40: sways from
    side to side, raising her arms and spreading her crown. 40-43: draws her head back. 43-56: SSSSSSSSSSSSSsssssss:
    jaws wide, fangs down, tongue flickering, trembling, dying away. 56-64: folds her fangs and sinks into her Idle."""
    f = t * ENTRANCE

    def k(*keys):
        return eased(f, list(keys))

    fall = 46 * (1 - (f / 10) ** 2) if f < 10 else 0.0  # faster and faster, like a dropped thing
    hiss = k((42, 0), (44, 1), (50, 1), (56, 0))
    shake = math.sin(f * 2.9) * hiss
    sway = math.sin(2 * math.pi * (f - 30) / 10) * k((29, 0), (31, 1), (38, 1), (41, 0))
    rise = k((10, 0), (22, 0), (30, 1), (60, 1), (66, 0))  # reared up tall (0 slumped or at rest)
    slump = k((9, 0), (11, 1), (14, 0.85), (22, 0.8), (28, 0))
    pose = {
        "root": P(z=fall, ry=1.2 * shake,
                  sq=k((0, 1.08), (9.5, 1.08), (11, 0.8), (13, 0.88), (22, 0.9), (28, 1.0))),
        **neck(0, -6 * slump + 4 * sway, 10 * slump + 7 * sway - 4 * k((40, 0), (43, 1), (50, 1), (56, 0)),
               -14 * slump + 8 * sway, head=4 * slump - 14 * sway + 3 * shake,
               stretch=1 + 0.12 * rise - 0.12 * slump + 0.04 * hiss),
        "crown": P(rx=k((0, -12), (9, -12), (11, 10), (15, 0)) - 6 * k((40, 0), (43, 1), (52, 1), (56, 0)),
                   wide=1 + k((28, 0), (38, 0.18), (54, 0.18), (62, 0)) + 0.03 * shake,
                   sq=1 + k((28, 0), (38, 0.06), (54, 0.06), (62, 0))),
        **tongue(k((0, 0), (9, 0), (12, 1), (22, 1), (28, 0), (40, 0), (58, 0), (64, 1))
                 + 0.5 * math.sin(f * 1.3) * hiss,
                 flick=34 * math.sin(f * 2.3) * hiss + 18 * math.sin(f * 1.1) * k((22, 0), (26, 1), (40, 1), (42, 0))),
        **arms(k((0, 1), (9, 1), (12, 0), (24, 0), (30, 0.2), (38, 1.1), (54, 1.1), (62, 0.15)),
               spread=k((30, 0), (38, 1), (54, 1), (62, 0.5))),
        **coils(k((0, -30), (9, -30), (11, 10), (15, -4), (20, 0), (40, 0), (44, 12), (54, 12), (60, 0)),
                tips=k((0, -30), (9, -30), (12, 6), (18, 0)) + 8 * shake),
        **mouth(k((0, 0), (40, 0), (43, 1.0), (52, 1.0), (57, 0))),
        **fangs(k((41, 0), (43.5, 1.1), (45, 1.0), (54, 1.0), (57, 0))),
    }
    pose["head"] = P(ry=pose["head"][0][1], rx=k((9, 0), (12, 16), (22, 14), (30, -6), (40, -6), (43, -14), (50, -14),
                                                (57, 0)))
    return blend(pose, REST, k((60, 0), (66, 1)))


def cocked(q: float = 0.0) -> dict:
    """Reared up and drawn back to the viewer's right, ready to strike down to the left: arms high and claws spread as
    in her second frame, crown spread, jaws open, fangs down, tongue out straight. q (-1 to 1) trembles it."""
    return {
        **neck(0, 4, 12 + q, 8, head=-22 - 1.5 * q, stretch=1.1),
        "crown": P(rx=-4, wide=1.16 + 0.02 * q, sq=1.05),
        **tongue(0.5 * q, flick=22 * q),
        **arms(1.05, spread=1.0),
        **coils(12, tips=4 * q),
        **mouth(0.85 + 0.05 * q), **fangs(1.0),
    }


def windup(t: float) -> dict:
    """The tell, held: cocked to strike and trembling with it, twice a loop, her tongue flickering faster."""
    w = 2 * math.pi * t
    return {**cocked(math.sin(2 * w)), **tongue(0.5 * math.sin(2 * w), flick=26 * math.sin(4 * w))}


def attack(t: float) -> dict:
    """SSSSSS-SNAP. 0-4: rears back and to the viewer's right, jaws open (Windup's pose). 4-8: strikes down to the left
    in a long arc, her body stretching, jaws wide, her tongue drawn in, her clawed left hand thrown out ahead of her.
    8: the bite lands, jaws snapping shut, her head low at her left side. 8-12: holds on, then lets go. 12-18: back to
    Idle's first pose."""
    f = t * ATTACK

    def k(*keys):
        return eased(f, list(keys))

    reach = k((0, 0), (4, 0), (5, 0.1), (8, 1), (10, 0.95), (13, 0.3))  # 0 drawn back, 1 struck
    back = k((0, 0), (4, 1), (5, 1), (8, 0))
    strike = {
        **neck(0, 4 * back - 16 * reach, 12 * back - 36 * reach, 8 * back - 42 * reach,
               head=-22 * back + 102 * reach, stretch=1 + 0.1 * back + 0.2 * reach),
        "crown": P(rx=-4 * back - 14 * reach, wide=1 + 0.16 * back + 0.06 * reach, sq=1 + 0.05 * back),
        **tongue(0.5 * math.sin(f * 1.2) * back, flick=22 * math.sin(f * 2.4) * back,
                 out=k((0, 1), (5, 1), (7.5, 0.35), (11, 0.35), (14, 1))),  # drawn in as she bites
        **arms(1.05 * back + 0.3 * reach, spread=back + 0.6 * reach, left=1.05 * back + 0.5 * reach),
        **coils(12 * back + 6 * reach, tips=0, right=12 * back - 14 * reach),
        **mouth(k((0, 0), (4, 0.85), (6, 1.0), (7.2, 1.0), (8, 0.2), (11, 0.2), (13, 0))),
        **fangs(k((0, 0), (3, 1.0), (12, 1.0), (15, 0))),
    }
    strike["head"] = P(ry=strike["head"][0][1], rx=k((0, 0), (4, -8), (8, 10), (12, 4), (14, 0)))
    return blend(strike, REST, max(k((0, 1), (2.5, 0)), k((12, 0), (18, 1))))


CLIPS = {"Entrance": (entrance, ENTRANCE, False), "Idle": (idle, 24, True), "Windup": (windup, WINDUP, True),
         "Attack": (attack, ATTACK, False)}


# -- building and rendering ---------------------------------------------------------------------------------------

def build() -> dict:
    data = json.loads((OUT / "serpentis_mesh.json").read_text())
    scene = bpy.context.scene
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
    scene.name = SCENE
    scene.render.fps = kit.FPS
    scene.frame_start, scene.frame_end = 0, ENTRANCE
    body, n_verts, n_faces, palette = build_model(scene, data)
    rig = build_rig(scene, data, body)
    # Her neck stretches as she rears and strikes, a stretch at a time (one doesn't stretch the next); her head and
    # arms don't stretch with it.
    for bone in ("body_3", "head", "arm_l", "arm_r"):
        rig.data.bones[bone].inherit_scale = "NONE"
    cam =bpy.data.objects.new(f"{TAG}_camera", bpy.data.cameras.new(f"{TAG}_camera"))
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
    glb = OUT / "serpentis.glb"
    bpy.ops.export_scene.gltf(
        filepath=str(glb), export_format="GLB", use_active_scene=True,
        export_animations=True, export_animation_mode="ACTIONS", export_force_sampling=True,
        export_frame_range=False, export_anim_slide_to_zero=False, export_reset_pose_bones=True,
        export_skins=True, export_def_bones=False, export_yup=True, export_apply=False,
    )
    blend_file = OUT / "serpentis.blend"
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
    """A few frames of a clip, to check the poses: serpentis/test/<clip>_<frame>.png."""
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
