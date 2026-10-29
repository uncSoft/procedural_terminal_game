"""Spike: King Mouse rigged, animated and rendered in Blender, the Goblin King's way (build_king.py), from the front.

Reads the model inflate_mouse.py wrote (king_mouse/mouse_mesh.json). Runs headless:

    B=/Applications/Blender.app/Contents/MacOS/Blender
    $B -b --factory-startup --python spikes/goblin3d/build_mouse.py -- build         # king_mouse/king_mouse.glb + .blend
    $B -b spikes/goblin3d/king_mouse/king_mouse.blend --python spikes/goblin3d/build_mouse.py -- frames
    $B -b spikes/goblin3d/king_mouse/king_mouse.blend --python spikes/goblin3d/build_mouse.py -- test Attack 0 5 8

Four clips at 24 fps, all framed alike so his feet stay on the same spot: Entrance (once; ends on Idle's first pose),
Idle (loops), Windup (loops: how he stands while a heavy blow is coming) and Attack (once; from Idle's first pose back
to it). "frames" renders them from the front into king_mouse/frames_hd/<clip>/0/<frame>.png, 256 pixels a side,
toon-shaded in his sprite's colours, for reduce.py to shrink.
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

TAG = kit.TAG = "king_mouse"  # the King's helpers name and find what they make by it
OUT = HERE / "king_mouse"
SCENE = "KingMouse"
SPAN, ELEVATION = 48, 12  # the frame shows 48 sprite pixels across, looking down a little, as the King's did
JAW_DROP, MOUTH = 1.2, 1.7  # how far his chin drops wide open, and his mouth's height shut (its bone), in pixels
TAIL = 5  # bones


# -- poses ------------------------------------------------------------------------------------------------------------
# As in build_king.py: turns in degrees about the rig's axes (x to the viewer's right, y away, z up), nudges in pixels,
# a squash. His arms hang, so a negative turn about x swings one forward and up (-180 is straight up), and a turn about
# y lifts it out sideways (left arm positive, right arm negative). A fist turns the same way at the wrist. His claws'
# size runs from 0 (sheathed in the fist) to 1. The tail turns about y to swing in the picture: negative curls it up.

def blend(a: dict, b: dict, u: float) -> dict:
    """Pose a, moved u of the way (0 to 1) toward pose b."""
    def mix(p, q):
        return tuple(x + (y - x) * u for x, y in zip(p, q))
    return {bone: tuple(mix(p, q) for p, q in zip(a.get(bone, P()), b.get(bone, P()))) for bone in {*a, *b}}


def mouth(opened: float) -> dict:
    """His jaw dropped and his mouth stretched to match: 0 shut, 1 wide open."""
    drop = JAW_DROP * opened
    return {"jaw": P(z=-drop), "mouth": P(sq=(MOUTH + drop) / MOUTH, wide=1.0)}


def claws(size: float) -> dict:
    return {"claws_l": P(size=max(size, 0.02)), "claws_r": P(size=max(size, 0.02))}


def tail(base: float = 0.0, curl: float = 0.0, wave: float = 0.0, phase: float = 0.0, lag: float = 0.8) -> dict:
    """The tail's bones: the first turned by base, every one curled by curl, and a wave running down it."""
    return {f"tail_{n + 1}": P(ry=(base if n == 0 else 0) + curl + wave * math.sin(phase - lag * n))
            for n in range(TAIL)}


def idle(t: float) -> dict:
    """Ready to fight: breathing deep, his nose twitching, fists flexing, ears flicking, tail swaying."""
    w = 2 * math.pi * t
    sink = 0.5 - 0.5 * math.cos(w)
    return {
        "root": P(sq=1 - 0.03 * sink),
        "torso": P(z=-0.25 * sink),
        "head": P(rx=-2 * math.sin(w - 0.7) + 1.2 * math.sin(2 * w)),
        "ear_l": P(ry=5 * math.sin(w - 1.0)), "ear_r": P(ry=-5 * math.sin(w - 1.0)),
        "arm_l": P(rx=-8 - 3 * math.sin(w - 0.4), ry=9 + 1.5 * sink),
        "arm_r": P(rx=-8 - 3 * math.sin(w - 0.4), ry=-9 - 1.5 * sink),
        "fist_l": P(rx=-12 - 5 * math.sin(w - 1.0)), "fist_r": P(rx=-12 - 5 * math.sin(w - 1.0)),
        **claws(0),
        **tail(wave=5, phase=w),
    }


REST = idle(0.0)
ENTRANCE, WINDUP, ATTACK = 72, 10, 20


def entrance(t: float) -> dict:
    """King Mouse arrives. 0-10: he jumps down from above (his stairs), fists up, tail streaming. 10: his feet hit
    the floor. 10-22: lands in a deep crouch, both fists down on the floor, and holds it, glaring. 22-33: rises tall,
    chest out, nose in the air, and throws both arms up in a flex. 33-44: holds it, pumping it twice: VEERY BIG
    MOUSE. 44-47: crosses his arms, coiling. 47-50: flings them wide, and his claws spring out: SHINK. 50-60: squeeeeeeeEEAKKK, mouth wide,
    trembling, tail lashing. 60-68: claws in, and he drops into his Idle stance."""
    f = t * ENTRANCE

    def k(*keys):
        return eased(f, list(keys))

    fall = 46 * (1 - (f / 10) ** 2) if f < 10 else 0.0  # faster and faster, like a dropped thing
    shake = math.sin(f * 2.7) * k((49, 0), (51, 1), (59, 1), (61, 0))  # the squeak's tremble
    lash = k((48, 0), (51, 1), (59, 1), (62, 0))
    pump = k((33, 0), (35, 1), (36.5, 0), (39, 1), (40.5, 0))  # the flex, squeezed harder twice
    pose = {
        "root": P(z=fall + 0.4 * pump + k((46, 0), (49, 1.2), (51, 0.6), (59, 0.6), (61, 0)),
                  ry=1.5 * shake,
                  sq=k((0, 1.12), (9.5, 1.12), (11, 0.72), (13, 0.82), (22, 0.8), (29, 1.02), (32, 1.04),
                       (44, 1.03), (47, 0.9), (50, 1.1), (59, 1.06), (62, 0.94))),
        "torso": P(rx=k((9, 0), (12, 28), (22, 24), (29, -8), (44, -6), (47, 14), (50, -12), (59, -10), (63, 0))),
        "head": P(rx=k((0, 6), (9, 6), (12, -18), (22, -20), (29, -12), (44, -10), (47, 10), (50, -22), (59, -20),
                       (63, 0)) + 2 * shake,
                  rz=k((33, 0), (35, 7), (38, -6), (41, 5), (44, 0)) + 3 * shake),
        "ear_l": P(rx=k((46, 0), (50, -40), (59, -40), (63, 0)),
                   ry=k((0, 25), (9, 25), (12, -35), (15, 10), (18, 0)) + 6 * shake),
        "ear_r": P(rx=k((46, 0), (50, -40), (59, -40), (63, 0)),
                   ry=-k((0, 25), (9, 25), (12, -35), (15, 10), (18, 0)) - 6 * shake),
        "arm_l": P(rx=k((0, -165), (9, -165), (12, -28), (22, -26), (28, -20), (33, -12), (44, -12), (47, -95),
                        (50, -10), (59, -10), (63, -8)) + 4 * shake,
                   ry=k((0, 25), (9, 25), (12, 14), (22, 14), (28, 10), (33, 105), (44, 105), (47, -50), (50, 125),
                        (59, 120), (63, 9)) - 8 * pump),
        "arm_r": P(rx=k((0, -165), (9, -165), (12, -28), (22, -26), (28, -20), (33, -12), (44, -12), (47, -85),
                        (50, -10), (59, -10), (63, -8)) - 4 * shake,
                   ry=k((0, -25), (9, -25), (12, -14), (22, -14), (28, -10), (33, -105), (44, -105), (47, 50),
                        (50, -125), (59, -120), (63, -9)) + 8 * pump),
        "fist_l": P(rx=k((9, 0), (12, -25), (22, -25), (28, -12), (33, 0), (44, 0), (47, -40), (50, 0), (60, 0),
                         (64, -12)),
                    ry=k((28, 0), (33, 85), (44, 85), (47, 0)) + 12 * pump),  # bent up at the wrist: the flex
        "fist_r": P(rx=k((9, 0), (12, -25), (22, -25), (28, -12), (33, 0), (44, 0), (47, -40), (50, 0), (60, 0),
                         (64, -12)),
                    ry=-k((28, 0), (33, 85), (44, 85), (47, 0)) - 12 * pump),
        **claws(k((47, 0), (49.5, 1.25), (52, 1.0), (60, 1.0), (63, 0))),
        **mouth(k((0, 0.5), (9, 0.5), (12, 0), (46, 0), (49, 1.0), (59, 1.0), (62, 0))),
        **tail(base=k((0, -80), (9, -80), (12, 8), (16, -12), (20, 4), (24, 0)),
               curl=k((0, -12), (9, -12), (12, 4), (18, 0)) - 10 * lash,  # lashing, but never through the floor
               wave=5 + 14 * lash, phase=2 * math.pi * f / (6 if 48 <= f <= 62 else 24)),
    }
    return blend(pose, REST, k((61, 0), (68, 1)))


def cocked(q: float = 0.0) -> dict:
    """Coiled to strike: his left fist (the viewer's right) drawn back high and wide, claws out, his right held out low
    at his side, claws ready, leaning in, mouth open on a squeak, ears back, tail up. q (-1 to 1) trembles it."""
    return {
        "root": P(sq=1.05 + 0.01 * q),
        "torso": P(rx=8 + q, ry=8, rz=14),
        "head": P(rx=-4 + 1.5 * q, ry=-6, rz=-8),
        "ear_l": P(rx=-35, ry=-8 + 3 * q), "ear_r": P(rx=-35, ry=8 - 3 * q),
        "arm_r": P(rx=-25 - 3 * q, ry=-158), "fist_r": P(rx=-20),
        "arm_l": P(rx=-35 + 3 * q, ry=40), "fist_l": P(rx=-30),
        **claws(1.1),
        **mouth(0.85 + 0.1 * q),
        **tail(base=-30, curl=-6),
    }


def windup(t: float) -> dict:
    """The tell, held: cocked to strike and trembling with it, twice a loop, the tail quivering."""
    w = 2 * math.pi * t
    return {**cocked(math.sin(2 * w)), **tail(base=-30, curl=-6, wave=6, phase=2 * w)}


def attack(t: float) -> dict:
    """BEWARE THE CLAWS. 0-4: cocks his clawed fist back high (Windup's pose). 4-8: rakes it down in a big arc,
    twisting his shoulder into it, his other arm dropping back. 8: the blow lands, claws low and out at his side.
    8-12: follows through. 12-18: back to Idle's first pose."""
    f = t * ATTACK

    def k(*keys):
        return eased(f, list(keys))

    strike = {
        "root": P(z=k((0, 0), (4, 0.5), (7, 0.3), (8, 0)),
                  sq=k((0, 1.0), (4, 1.05), (6, 1.02), (8, 0.88), (10, 0.9), (13, 0.99))),
        "torso": P(rx=k((0, 0), (4, 8), (8, 16), (11, 13), (14, 2)),
                   ry=k((0, 0), (4, 8), (8, 6), (11, 4), (14, 0)),
                   rz=k((0, 0), (4, 14), (8, -12), (11, -9), (14, 0))),
        "head": P(rx=k((0, 0), (4, -4), (8, 0), (12, 0)),
                  ry=k((0, 0), (4, -6), (8, -4), (12, 0)),
                  rz=k((0, 0), (4, -8), (8, 8), (12, 0))),
        "ear_l": P(rx=k((0, 0), (4, -35), (11, -30), (15, 0))),
        "ear_r": P(rx=k((0, 0), (4, -35), (11, -30), (15, 0))),
        "arm_r": P(rx=k((0, -8), (4, -25), (5, -28), (8, -28), (10, -24), (13, -12)),
                   ry=k((0, -9), (4, -158), (5, -158), (8, -52), (10, -38), (13, -12))),
        "fist_r": P(rx=k((0, -12), (4, -20), (8, -35), (12, -12))),
        "arm_l": P(rx=k((0, -8), (4, -35), (8, -20), (11, -18), (14, -10)),
                   ry=k((0, 9), (4, 40), (8, 24), (11, 20), (14, 12))),
        "fist_l": P(rx=k((0, -12), (4, -30), (8, -20), (13, -12))),
        **claws(k((0, 0), (3, 1.2), (5, 1.1), (12, 1.0), (16, 0))),
        **mouth(k((0, 0), (4, 0.9), (9, 0.8), (14, 0))),
        **tail(base=k((0, 0), (4, -30), (8, 8), (12, 0)), wave=5, phase=2 * math.pi * f / 20),
    }
    return blend(strike, REST, max(k((0, 1), (2.5, 0)), k((12, 0), (18, 1))))


CLIPS = {"Entrance": (entrance, ENTRANCE, False), "Idle": (idle, 24, True), "Windup": (windup, WINDUP, True),
         "Attack": (attack, ATTACK, False)}


# -- building and rendering ---------------------------------------------------------------------------------------

def build() -> dict:
    data = json.loads((OUT / "mouse_mesh.json").read_text())
    scene = bpy.context.scene
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
    scene.name = SCENE
    scene.render.fps = kit.FPS
    scene.frame_start, scene.frame_end = 0, ENTRANCE
    body, n_verts, n_faces, palette = build_model(scene, data)
    rig = build_rig(scene, data, body)
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
    glb = OUT / "king_mouse.glb"
    bpy.ops.export_scene.gltf(
        filepath=str(glb), export_format="GLB", use_active_scene=True,
        export_animations=True, export_animation_mode="ACTIONS", export_force_sampling=True,
        export_frame_range=False, export_anim_slide_to_zero=False, export_reset_pose_bones=True,
        export_skins=True, export_def_bones=False, export_yup=True, export_apply=False,
    )
    blend_file = OUT / "king_mouse.blend"
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
    """A few frames of a clip, to check the poses: king_mouse/test/<clip>_<frame>.png."""
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


if "TASK" in globals():
    RESULT = main(globals()["TASK"])
elif __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else ["build"]
    print("RESULT", json.dumps(main(*argv)))
