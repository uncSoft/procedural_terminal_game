"""Spike: the Drowned Abbot rigged, animated and rendered in Blender, the way build_serpentis.py did Serpentis, from the
front.

Reads the model inflate_abbot.py wrote (drowned_abbot/abbot_mesh.json). Runs headless:

    B=/Applications/Blender.app/Contents/MacOS/Blender
    $B -b --factory-startup --python spikes/goblin3d/build_abbot.py -- build      # drowned_abbot/drowned_abbot.glb + .blend
    $B -b spikes/goblin3d/drowned_abbot/drowned_abbot.blend --python spikes/goblin3d/build_abbot.py -- frames
    $B -b spikes/goblin3d/drowned_abbot/drowned_abbot.blend --python spikes/goblin3d/build_abbot.py -- test Attack 0 5 8

Four clips at 24 fps, all framed alike so his hem stays on the same spot: Entrance (once; ends on Idle's first pose),
Idle (loops), Windup (loops: his tell, held) and Attack (once; from Idle's first pose back to it). "frames" renders
them from the front into drowned_abbot/frames_hd/<clip>/0/<frame>.png, 256 pixels a side, toon-shaded in his sprite's
colours, for reduce.py to shrink.
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

TAG = kit.TAG = "drowned_abbot"  # the King's helpers name and find what they make by it
kit.GROUND = 23  # his drips reach a pixel lower than the King's boots: the floor is under them, framed the same
OUT = HERE / "drowned_abbot"
SCENE = "DrownedAbbot"
SPAN, ELEVATION = 48, 12  # as the King, King Mouse and Serpentis were framed


# -- poses ------------------------------------------------------------------------------------------------------------
# As in build_king.py: turns in degrees about the rig's axes (x to the viewer's right, y away, z up), nudges in pixels,
# a squash. A positive turn about y tips the top of a part toward the viewer's right. arm() turns both arms the same
# way out: positive raises an arm out from his side and up. His censer's chain is swung by its own angle from hanging
# straight down, whatever his arm is doing (positive swings it toward the viewer's left), and let out longer by `out`.

def arm(side: str, shoulder: float = 0.0, elbow: float = 0.0, wrist: float = 0.0) -> dict:
    """His arm on the viewer's left ("l") or right ("r"), raised out from his side by `shoulder` degrees and bent
    further out by `elbow` and `wrist` (negative: back in)."""
    sign = 1 if side == "l" else -1
    return {f"arm_{side}": P(ry=sign * shoulder), f"forearm_{side}": P(ry=sign * elbow),
            f"hand_{side}": P(ry=sign * wrist)}


def censer(pose: dict, swing: float = 0.0, out: float = 1.0) -> dict:
    """The chain turned so it hangs `swing` degrees from straight down, whatever his body and arm have done."""
    held = sum(pose.get(bone, P())[0][1] for bone in ("root", "body", "chest", "arm_r", "forearm_r", "hand_r"))
    return {"chain": P(ry=swing - held, sq=out, wide=1.0)}


def mouth(opened: float) -> dict:
    """0 shut (and gone, as in his sprite), 1 wide open."""
    o = min(max(opened, 0.0), 1.2)
    if o < 0.02:
        return {"mouth": P(size=0.01)}
    return {"mouth": P(sq=o, wide=0.55 + 0.45 * min(o, 1.0))}


def flat(pose: tuple, side: float, height: float = 1.0) -> tuple:
    """A pose for a bone standing up (the root, the hem), squashed across the picture and up it but not toward the
    viewer, so his hem doesn't come forward and dip below the floor in the picture as it flares."""
    return pose[0], pose[1], (side, height, 1.0)


def splashes(landing: float = 0.0, hit: float = 0.0) -> dict:
    return {"splash_l": P(size=max(landing, 0.02)), "splash_r": P(size=max(landing, 0.02)),
            "splash_hit": P(size=max(hit, 0.02))}


def whip(t: float, keys: list) -> float:
    """A value running straight between (time, value) keys, without easing: for things swung hard."""
    if t <= keys[0][0]:
        return keys[0][1]
    for (t0, v0), (t1, v1) in zip(keys, keys[1:]):
        if t <= t1:
            return v0 + (v1 - v0) * (t - t0) / (t1 - t0)
    return keys[-1][1]


def idle(t: float) -> dict:
    """Saying his mass: he sinks a pixel and rises again, as in his two frames, his hem on the floor; his censer sways
    on its chain, his head nods, and his mouth mutters once."""
    w = 2 * math.pi * t
    bob = 0.5 - 0.5 * math.cos(w)  # 0 up, as in his first frame; 1 sunk, as in his second
    pose = {
        "body": P(sq=1 - 0.09 * bob, wide=1 + 0.01 * bob, ry=0.8 * math.sin(w)),
        "chest": P(sq=1 - 0.04 * bob, wide=1.0, ry=-0.6 * math.sin(w - 0.5)),
        "head": P(rx=2.5 * math.sin(w - 0.8), ry=-1.0 * math.sin(w - 1.0), z=-0.25 * bob),
        **arm("l", 2.5 * math.sin(w - 1.4)), **arm("r", 2.5 * math.sin(w - 1.4)),
        **mouth(0.55 * max(0.0, math.sin(w - 0.6)) ** 2),
        "drip": P(sq=1 + 0.4 * bob, wide=1.0),
        **splashes(),
    }
    pose.update(censer(pose, swing=7 * math.sin(w - 1.6)))
    return pose


REST = idle(0.0)
OUT_AT_HIT = 5.1  # how far his censer's chain is let out when it strikes, as many times its length
ENTRANCE, WINDUP, ATTACK = 72, 10, 20


def entrance(t: float) -> dict:
    """The Drowned Abbot arrives. 0-10: he drops from the roof like something sinking, his cope billowing up round
    him, his arms floating, his censer trailing above. 10: his hem hits the floor in a splash of black water. 10-22: he
    stands hunched where he fell, his censer swinging. 22-30: straightens. 30-40: raises his censer high and his other
    hand, and throws his head back. 40-54: chants, backwards, swinging his censer. 54-64: lowers his arms into his
    Idle."""
    f = t * ENTRANCE

    def k(*keys):
        return eased(f, list(keys))

    fall = 46 * (1 - (f / 10) ** 2) if f < 10 else 0.0  # faster and faster, like a dropped thing
    squash = k((0, 1.06), (9.5, 1.06), (10.5, 0.84), (13, 0.95), (17, 1.0))
    hunch = k((10, 0), (12, 1), (22, 1), (30, 0))
    lift = k((28, 0), (38, 1), (54, 1), (63, 0))  # arms raised, censer high
    chant = k((40, 0), (42, 1), (52, 1), (55, 0))
    flap = 0.5 + 0.5 * math.cos(2 * math.pi * (f - 42) / 4.0)
    pose = {
        "root": flat(P(z=fall), 1 / math.sqrt(squash), squash),
        "hem": flat(P(z=k((0, 2.5), (9, 2.5), (10, 0))), k((0, 1.22), (9, 1.22), (10.5, 1.3), (14, 1.06), (20, 1.0))),
        "body": P(rx=8 * hunch, sq=1 - 0.05 * hunch + 0.03 * lift, wide=1.0, ry=4 * math.sin(f * 0.6) * chant),
        "chest": P(rx=8 * hunch - 4 * lift),
        "head": P(rx=k((0, -10), (9, -10), (11, 14), (12, 24), (22, 22), (30, 0), (34, -6), (38, -14), (54, -14),
                       (60, 0)) - 4 * flap * chant,
                  ry=6 * lift),
        **arm("l", k((0, 70), (9, 70), (11, 8), (14, 0), (28, 0), (38, 70), (54, 70), (63, 0)),
              k((0, 30), (9, 30), (11, 0), (28, 0), (38, 18), (54, 18), (63, 0)),
              k((28, 0), (38, 40), (54, 40), (63, 0))),
        **arm("r", k((0, 70), (9, 70), (11, 8), (14, 0), (28, 0), (38, 70), (54, 70), (63, 0)),
              k((0, 30), (9, 30), (11, 0), (28, 0), (38, 15), (54, 15), (63, 0)),
              k((28, 0), (38, 40), (54, 40), (63, 0))),
        **mouth(k((0, 0), (30, 0), (38, 0.9), (42, 0.9), (54, 0.9), (58, 0)) * (1 - 0.7 * flap * chant)),
        "drip": P(sq=1 + 0.3 * lift, wide=1.0),
        **splashes(landing=whip(f, [(10, 0), (10.5, 0.8), (13, 1.3), (14, 1.4)]) if f < 14.5 else 0.0),
    }
    swing = (k((0, 170), (9, 170), (11, 70), (13, -35), (16, 22), (19, -12), (22, 6), (26, 0))
             + 32 * math.sin(2 * math.pi * (f - 40) / 10) * k((38, 0), (42, 1), (52, 1), (56, 0)))
    pose.update(censer(pose, swing=swing))
    return blend(pose, REST, k((60, 0), (66, 1)))


def raised(q: float = 0.0) -> dict:
    """His tell: his censer raised high on the viewer's right, his other hand up, his head thrown back, chanting.
    q (-1 to 1) rocks it."""
    pose = {
        "body": P(sq=1.03, wide=1.0),  # upright: tilted, his stole breaks up once he's shrunk
        "chest": P(),
        "head": P(rx=-10 - 2 * q, ry=5),
        **arm("r", 70, 15, 40),
        **arm("l", 70 + 2 * q, 18, 40 + 6 * q),
        **mouth(0.75 + 0.25 * q),
        "drip": P(sq=1.3 + 0.3 * q, wide=1.0),
        **splashes(),
    }
    pose.update(censer(pose, swing=14 * q))
    return pose


def windup(t: float) -> dict:
    """The tell, held: censer up and swinging, chanting, twice a loop."""
    return raised(math.sin(4 * math.pi * t))


def attack(t: float) -> dict:
    """0-4: raises his censer (Windup's pose). 4-8: whirls it up over his head and down out to his side on its chain,
    let out long. 8: it smashes into the floor on the viewer's right in a splash of black water. 8-12: holds it there.
    12-18: reels it in, back to Idle's first pose."""
    f = t * ATTACK

    def k(*keys):
        return eased(f, list(keys))

    up = k((0, 0), (4, 1), (5.5, 1), (8, 0))
    strike = k((5.5, 0), (8, 1), (11, 1), (15, 0))

    def swung(*keys):  # raised by 4, drawn up a little more, then brought down hard
        return whip(f, list(keys)) if 4 <= f <= 8 else k(*keys)

    pose = {
        "body": P(ry=6 * strike, sq=1 + 0.03 * up - 0.04 * strike, wide=1.0),
        "chest": P(ry=4 * strike),
        "head": P(rx=-10 * up + 8 * strike, ry=5 * up + 4 * strike),
        **arm("r", swung((0, 0), (4, 70), (5.5, 88), (8, 18), (11, 18), (15, 0)),
              swung((0, 0), (4, 15), (5.5, 22), (8, 5), (11, 5), (15, 0)),
              swung((0, 0), (4, 40), (5.5, 40), (8, 10), (11, 10), (15, 0))),
        **arm("l", k((0, 0), (4, 70), (5.5, 70), (8, 35), (11, 35), (15, 0)),
              k((0, 0), (4, 18), (8, 20), (11, 20), (15, 0)), k((0, 0), (4, 40), (8, 10), (15, 0))),
        **mouth(0.75 * up + k((6, 0), (8, 1.1), (11, 1.0), (14, 0))),
        "drip": P(sq=1 + 0.3 * up, wide=1.0) if not 7.5 <= f <= 14 else P(size=0.01),  # shaken off as it hits
        **splashes(hit=k((8, 0), (8.6, 0.75), (12, 1.35)) if f < 12.5 else 0.0),
    }
    # The censer whirls round the far side of his hand (the viewer's left of it), over the top and down, faster and
    # faster, and is reeled back in to hang.
    whirl = whip(f, [(4, 0), (5, 20), (6, 165), (7, 250), (8, 325)]) if f < 11 else k((11, 325), (15, 360))
    pose.update(censer(pose, swing=whirl, out=whip(f, [(4, 1), (6, 3), (8, OUT_AT_HIT)]) if f < 8
                       else k((8, OUT_AT_HIT), (11, OUT_AT_HIT), (16, 1))))
    return blend(pose, REST, max(k((0, 1), (1, 0)), k((14, 0), (18, 1))))


CLIPS = {"Entrance": (entrance, ENTRANCE, False), "Idle": (idle, 24, True), "Windup": (windup, WINDUP, True),
         "Attack": (attack, ATTACK, False)}


# -- building and rendering ---------------------------------------------------------------------------------------

def build() -> dict:
    data = json.loads((OUT / "abbot_mesh.json").read_text())
    scene = bpy.context.scene
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
    scene.name = SCENE
    scene.render.fps = kit.FPS
    scene.frame_start, scene.frame_end = 0, ENTRANCE
    body, n_verts, n_faces, palette = build_model(scene, data)
    rig = build_rig(scene, data, body)
    # He bobs by squashing his cope; his chest, head and arms ride on it without squashing, and his censer keeps its
    # size when its chain is let out.
    for bone in ("chest", "head", "arm_l", "arm_r", "censer"):
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
    glb = OUT / "drowned_abbot.glb"
    bpy.ops.export_scene.gltf(
        filepath=str(glb), export_format="GLB", use_active_scene=True,
        export_animations=True, export_animation_mode="ACTIONS", export_force_sampling=True,
        export_frame_range=False, export_anim_slide_to_zero=False, export_reset_pose_bones=True,
        export_skins=True, export_def_bones=False, export_yup=True, export_apply=False,
    )
    blend_file = OUT / "drowned_abbot.blend"
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
    """A few frames of a clip, to check the poses: drowned_abbot/test/<clip>_<frame>.png."""
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
