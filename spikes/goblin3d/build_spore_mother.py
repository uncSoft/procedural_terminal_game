"""Spike: the Spore Mother rigged, animated and rendered in Blender, the way build_thornmother.py did the Thornmother,
from the front.

Reads the model inflate_spore_mother.py wrote (spore_mother/spore_mother_mesh.json). Runs headless:

    B=/Applications/Blender.app/Contents/MacOS/Blender
    $B -b --factory-startup --python spikes/goblin3d/build_spore_mother.py -- build    # spore_mother/spore_mother.glb + .blend
    $B -b spikes/goblin3d/spore_mother/spore_mother.blend --python spikes/goblin3d/build_spore_mother.py -- frames
    $B -b spikes/goblin3d/spore_mother/spore_mother.blend --python spikes/goblin3d/build_spore_mother.py -- test Attack 0 5 8

Four clips at 24 fps, all framed alike so she sits on the same spot: Entrance (once; ends on Idle's first pose), Idle
(loops), Windup (loops: her tell, held) and Attack (once; from Idle's first pose back to it). "frames" renders them
from the front into spore_mother/frames_hd/<clip>/0/<frame>.png, 256 pixels a side, toon-shaded in her sprite's
colours, for reduce.py to shrink.

She's one of the four that fight as the Humongous Fungus, so she's mostly seen small: everything she does is big and
plain in the picture's plane, and she butts the way the bosses strike, out to the viewer's right.
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

TAG = kit.TAG = "spore_mother"  # the King's helpers name and find what they make by it
kit.GROUND = 23  # she sits a pixel lower than the King's boots: the floor is under her, framed the same
OUT = HERE / "spore_mother"
SCENE = "SporeMother"
SPAN, ELEVATION = 48, 12  # as every boss was framed
MESH = json.loads((OUT / "spore_mother_mesh.json").read_text())
NECK = MESH["bones"]["body"]["head"][1] - MESH["bones"]["cap"]["head"][1]  # how far her cap sits up her body


# -- poses ------------------------------------------------------------------------------------------------------------
# As in build_king.py: turns in degrees about the rig's axes (x to the viewer's right, y away, z up), nudges in pixels,
# a squash. A positive turn about y tips the top of a part toward the viewer's right. Her body turns about the bottom
# she sits on, and carries her cap; her cap turns about the middle of its underside, on top of whatever her body does.

def plump(**turns) -> tuple:
    """A pose for her body (P's turns, nudges and squash), squashed and stretched across the picture and up it but
    never toward the viewer: a body made deeper comes forward, and from 12 degrees above its bottom then looks lower
    than the floor."""
    turn, nudge, (wide, sq, _) = P(**turns)
    return turn, nudge, (wide, sq, 1.0)


def glow(bright: float = 1.0, glint: float = 1.0) -> dict:
    """Her glow: the bright green over the dim one, 0 all dim (as in her second frame) to 1 all bright (her first),
    and past it to flare; and her glint's size."""
    return {"glow": P(size=max(bright, 0.02)), "glint": P(size=max(glint, 0.02))}


def spores(puff: float = 0.0, burst: float = 0.0) -> dict:
    return {"puff": P(size=max(puff, 0.02)), "burst": P(size=max(burst, 0.02))}


def whip(t: float, keys: list) -> float:
    """A value running straight between (time, value) keys, without easing: for things thrown hard."""
    if t <= keys[0][0]:
        return keys[0][1]
    for (t0, v0), (t1, v1) in zip(keys, keys[1:]):
        if t <= t1:
            return v0 + (v1 - v0) * (t - t0) / (t1 - t0)
    return keys[-1][1]


def idle(t: float) -> dict:
    """Humming to the others: she draws herself up a pixel and sinks again, as in her two frames, her glow dimming as
    she rises and brightening as she sinks. She doesn't sway: shrunk small, a sway jiggles her spots a pixel back and
    forth."""
    w = 2 * math.pi * t
    bob = 0.5 - 0.5 * math.cos(w)  # 0 low and bright, as in her first frame; 1 drawn up and dim, as in her second
    return {
        "body": plump(sq=1 + 0.075 * bob, wide=1 - 0.02 * bob),
        "cap": P(),
        **glow(1 - bob),
        **spores(),
    }


REST = idle(0.0)
ENTRANCE, WINDUP, ATTACK = 72, 10, 20
LAND = 18  # the frame she lands on


def entrance(t: float) -> dict:
    """The Spore Mother arrives, in her own time. 0-15: she floats down from the roof under her cap, spread like a
    parachute, her body swinging under it, her glow dim. 15-18: it lets go, and she drops the last bit. 18: she lands
    with a plump bump, and her cap flops down on her after. 18-26: she wobbles still. 26-33: she draws herself up,
    puffing her cap up big, and her glow comes on bright. 33: a puff of spores flies up out of her cap. 33-52: she
    hums, swaying, glowing. 52-64: she settles into her Idle."""
    f = t * ENTRANCE

    def k(*keys):
        return eased(f, list(keys))

    fall = 44 - 35 * f / 15 if f < 15 else 9 * (LAND - f) / (LAND - 15) if f < LAND else 0.0
    floating = k((0, 1), (13, 1), (17, 0))
    rock = math.sin(2 * math.pi * (f + 2) / 15) * floating
    swing = 18 * rock  # her body swings under her cap, which stays level and drifts the other way
    drift = -2.2 * rock
    hum = k((35, 0), (37, 1), (49, 1), (52, 0))
    body_sq = k((0, 1.05), (15, 1.05), (18, 0.84), (19, 0.76), (20.5, 1.07), (22.5, 0.96), (24.5, 1.02), (26, 1.0),
                (33, 1.13), (50, 1.13), (58, 1.0))
    lift = NECK * body_sq  # how far up her body her cap sits now
    s = math.radians(swing)
    pose = {
        "root": P(x=drift - lift * math.sin(s), z=fall + lift * (1 - math.cos(s))),
        "body": plump(sq=body_sq, wide=k((0, 0.98), (15, 0.98), (18, 1.09), (19, 1.14), (20.5, 0.97), (22.5, 1.02),
                                         (25, 1.0), (33, 0.97), (50, 0.97), (58, 1.0)),
                      ry=swing + 5 * math.sin(2 * math.pi * (f - 36) / 8) * hum),
        "cap": P(ry=-0.85 * swing - 3 * math.sin(2 * math.pi * (f - 37) / 8) * hum,
                 z=k((18, 0), (19.5, -0.5), (21, 0)),
                 sq=k((0, 0.86), (16, 0.86), (18, 0.9), (19.5, 0.8), (21.5, 1.1), (23.5, 0.96), (25.5, 1.0)),
                 wide=k((0, 1.14), (16, 1.14), (18, 1.12), (19.5, 1.17), (21.5, 0.97), (23.5, 1.02), (25.5, 1.0)),
                 size=k((26, 1.0), (31, 1.28), (33, 1.22), (50, 1.22), (58, 1.0))),
        **glow(k((0, 0.12), (17, 0.12), (19, 0.75), (22, 0.2), (27, 0.25), (33, 1.25), (50, 1.25), (56, 1.0)),
               k((0, 0.9), (29, 1.0), (33, 1.5), (50, 1.5), (56, 1.0))),
        **spores(),
        "puff": P(z=whip(f, [(33, 0.0), (44, 4.0)]), size=whip(f, [(33, 0.0), (33.6, 0.55), (37, 1.0), (44, 1.4)])
                  if 33 <= f < 44.5 else 0.02),  # her spores, drifting up as they spread
    }
    return blend(pose, REST, k((56, 0), (64, 1)))


PUFFED = 1.28  # how big her cap puffs up to butt


def raised(q: float = 0.0) -> dict:
    """Her tell: her cap puffed up big and lowered at you like a ram's head (tipped toward the viewer's right, where
    she butts), her body crouched and leaning back to spring, her glow bright. q (-1 to 1) makes it quiver."""
    return {
        "body": plump(sq=0.88 - 0.012 * q, wide=1.05, ry=-10 + 0.8 * q),
        "cap": P(ry=56 + 2.5 * q, size=PUFFED + 0.015 * q),
        **glow(1.0, 1.15 + 0.1 * q),
        **spores(),
    }


def windup(t: float) -> dict:
    """The tell, held, quivering with it, twice a loop."""
    return raised(math.sin(4 * math.pi * t))


HIT = 8  # the frame her butt lands on


def attack(t: float) -> dict:
    """0-4: puffs her cap up and lowers it (Windup's pose). 4-5.5: crouches deeper, leaning back. 5.5-8: springs at
    the viewer's right, cap first, her body swinging in behind it. 8: her cap butts home, squashing on it, and spores
    burst off it where it hits, flying apart till 10. 8-12.5: she bounces back off it to where she was. 12.5: lands,
    and settles back into Idle's first pose by 18. Her cap stays aimed at what she butts (about 45 degrees), so its
    top, not its edge, is what hits."""
    f = t * ATTACK

    def k(*keys):
        return eased(f, list(keys))

    def thrown(*keys):  # eased into the crouch, then thrown hard
        return whip(f, list(keys)) if 5.5 <= f <= HIT else k(*keys)

    pose = {
        "root": P(x=thrown((0, 0), (4, 0), (5.5, -0.8), (HIT, 6.0), (9, 5.6), (12.5, 0)),
                  z=thrown((0, 0), (5.5, 0), (HIT, 1.2), (9, 1.3), (10.8, 2.0), (12.5, 0)) if f < 12.5 else 0.0),
        "body": plump(sq=thrown((0, 1.0), (4, 0.88), (5.5, 0.84), (7, 1.12), (HIT, 1.08), (9, 0.98), (11, 1.04),
                                (12.5, 0.88), (14.5, 1.03), (16, 1.0)),
                      wide=thrown((0, 1.0), (4, 1.05), (5.5, 1.07), (7, 0.96), (HIT, 0.97), (9, 1.01), (11, 0.98),
                                  (12.5, 1.07), (14.5, 0.99), (16, 1.0)),
                      ry=thrown((0, 0), (4, -10), (5.5, -13), (HIT, 24), (9, 20), (11, -2), (12.5, -5), (14, 0))),
        "cap": P(ry=thrown((0, 0), (4, 56), (5.5, 60), (HIT, 26), (9, 26), (11, 14), (13, 4), (15, 0)),
                 sq=k((7.6, 1.0), (HIT, 0.88), (9, 0.95), (10.5, 1.02), (12, 1.0)),
                 size=k((0, 1.0), (4, PUFFED), (HIT, PUFFED), (10, 1.18), (14, 1.0))),
        **glow(k((0, 1.0), (4, 1.0), (7.5, 1.0), (HIT, 1.25), (11, 1.0)),
               k((0, 1.0), (4, 1.15), (7.5, 1.15), (HIT, 1.5), (11, 1.0))),
        **spores(burst=whip(f, [(HIT - 0.4, 0.0), (HIT, 0.45), (HIT + 1, 0.75), (10.6, 1.1)])
                 if HIT - 0.4 <= f < 10.6 else 0.0),
    }
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
    # She squashes and stretches her body; her cap rides on it without squashing, puffing up by itself, and the spores
    # it puffs keep their own size whatever her cap does. (The burst hangs where her butt lands, on no bone of hers.)
    for bone in ("cap", "puff"):
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
    hit = crown(rig, "Attack", HIT)
    burst = MESH["bones"]["burst"]["head"]
    if max(abs(a - b) for a, b in zip(hit, burst)) > 0.5:  # the spores are made where it lands (inflate's BURST_AT)
        print(f"WARNING: her butt lands at {[round(c, 2) for c in hit]}, but her spores burst at {burst}")
    rig.animation_data.action = actions[0]
    scene.frame_set(0)
    toon(False)
    glb = OUT / "spore_mother.glb"
    bpy.ops.export_scene.gltf(
        filepath=str(glb), export_format="GLB", use_active_scene=True,
        export_animations=True, export_animation_mode="ACTIONS", export_force_sampling=True,
        export_frame_range=False, export_anim_slide_to_zero=False, export_reset_pose_bones=True,
        export_skins=True, export_def_bones=False, export_yup=True, export_apply=False,
    )
    blend_file = OUT / "spore_mother.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_file))
    return {"verts": n_verts, "faces": n_faces, "colours": palette, "bones": len(rig.data.bones),
            "clips": [a.name for a in actions], "glb_bytes": glb.stat().st_size, "hit": [round(c, 2) for c in hit]}


def crown(rig, clip: str, frame: int) -> tuple:
    """Where the top of her cap is at a frame of a clip, in the sprite's pixels (x, y, toward the viewer)."""
    rig.animation_data.action = bpy.data.actions[clip]
    bpy.context.scene.frame_set(frame)
    p = rig.matrix_world @ rig.pose.bones["cap"].tail
    return p.x / kit.S + kit.CENTRE, kit.GROUND - p.z / kit.S, -p.y / kit.S


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
    """A few frames of a clip, to check the poses: spore_mother/test/<clip>_<frame>.png."""
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
