"""Spike: the Sporefang Matriarch rigged, animated and rendered in Blender, as build_thornmother.py did the Thornmother,
from the front.

Reads the model inflate_matriarch.py wrote (sporefang_matriarch/matriarch_mesh.json). Runs headless:

    B=/Applications/Blender.app/Contents/MacOS/Blender
    $B -b --factory-startup --python spikes/goblin3d/build_matriarch.py -- build    # sporefang_matriarch/*.glb + .blend
    $B -b spikes/goblin3d/sporefang_matriarch/sporefang_matriarch.blend --python spikes/goblin3d/build_matriarch.py -- frames
    $B -b spikes/goblin3d/sporefang_matriarch/sporefang_matriarch.blend --python spikes/goblin3d/build_matriarch.py -- test Attack 0 5 8

Her legs stand on IK: each tarsus reaches for a foot bone (on the floor, under the root, for the six she stands on; on
her body for the raised back pair), three bones up, its knee bending toward a pole on her body. So her body can bob,
crouch and rear up while her feet stay planted, and a pose moves a leg by moving its foot.

Four clips at 24 fps, all framed alike so her feet stay on the same spot: Entrance (once; ends on Idle's first pose),
Idle (loops), Windup (loops: her tell, held) and Attack (once; from Idle's first pose back to it). "frames" renders
them from the front into sporefang_matriarch/frames_hd/<clip>/0/<frame>.png, 256 pixels a side, toon-shaded in her
sprite's colours, for reduce.py to shrink.
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

TAG = kit.TAG = "sporefang_matriarch"  # the King's helpers name and find what they make by it
OUT = HERE / "sporefang_matriarch"
SCENE = "SporefangMatriarch"
SPAN, ELEVATION = 48, 12  # as every boss before her was framed
MESH = json.loads((OUT / "matriarch_mesh.json").read_text())
LEGS = (1, 2, 3, 4)  # 1 the raised back pair, 2 the outer, 3 the middle, 4 the front pair
SPORED = (1, 2, 4, 5)  # the toadstools that puff spores


# -- poses ------------------------------------------------------------------------------------------------------------
# As in build_king.py: turns in degrees about the rig's axes (x to the viewer's right, y away, z up), nudges in pixels,
# a squash. A positive turn about y tips the top of a part toward the viewer's right (clockwise, as the viewer sees it);
# a positive turn about x tips it forward. A leg is posed by its foot: nudged out from her middle, up, toward the viewer.

def feet(n: int, out: float = 0.0, up: float = 0.0, fore: float = 0.0, side: str | None = None) -> dict:
    """Leg n's foot (the raised pair's tip) moved `out` from her middle, `up` and `fore` (toward the viewer), in pixels,
    on both sides or one."""
    pose = {}
    for s, sign in (("l", -1), ("r", 1)):
        if side in (None, s):
            pose[f"foot_{n}{s}"] = P(x=sign * out, y=-fore, z=up)
    return pose


def jaws(spread: float) -> dict:
    """Her fangs turned out from each other by `spread` degrees (negative snaps them shut past where they rest)."""
    return {"fang_l": P(ry=spread), "fang_r": P(ry=-spread)}


def venom(swell: float = 1.0, stretch: float = 1.0, fall: float = 0.0) -> dict:
    """The drop at each fang's tip: swell scales it (0 gone), stretch draws it down long, fall drops it."""
    drop = P(z=-fall, sq=stretch, wide=1.0, size=max(swell, 0.02))
    return {"drip_l": drop, "drip_r": drop}


def dripping(t: float) -> dict:
    """Venom dripping, once a loop: the drop draws down long, falls, and a new one swells at the tip."""
    if t < 0.6:
        u = t / 0.6
        return venom(1.2, 1.3 + 0.9 * u * u)
    if t < 0.82:
        u = (t - 0.6) / 0.22
        return venom(1.2 * (1 - 0.5 * u), 2.2 - 0.9 * u, fall=1.7 * u * u)
    u = (t - 0.82) / 0.18
    return venom(0.5 + 0.7 * u * u * (3 - 2 * u), 1.3)


def glint(on: bool) -> dict:
    """Her middle eyes lit white, as in her other frames."""
    return {"glint_l": P(size=1.0 if on else 0.02), "glint_r": P(size=1.0 if on else 0.02)}


def silk(length: float) -> dict:
    """Her line, from the top of the frame down to her back: 1 all of it, less pulled up out of sight, 0 gone."""
    return {"silk": P(sq=length, wide=1.0) if length > 0.02 else P(size=0.02)}


def spores(size: float) -> dict:
    return {f"puff_{n}": P(size=max(size, 0.02)) for n in SPORED}


def spray(size: float) -> dict:
    return {"burst": P(size=max(size, 0.02))}


def caps(shake: float, f: float) -> dict:
    """Her toadstools shaken, each a little out of step with the others."""
    return {f"ts_{n}": P(ry=shake * math.sin(1.7 * f + n), rx=0.5 * shake * math.sin(1.3 * f + 2 * n))
            for n in range(1, 6)}


def bump(t: float, at: float, width: float) -> float:
    """0 away from `at`, rising smoothly to 1 there (t and at in a loop's 0 to 1)."""
    d = min(abs(t - at), 1 - abs(t - at))
    return 0.5 + 0.5 * math.cos(math.pi * d / width) if d < width else 0.0


def whip(t: float, keys: list) -> float:
    """A value running straight between (time, value) keys, without easing: for things struck hard."""
    if t <= keys[0][0]:
        return keys[0][1]
    for (t0, v0), (t1, v1) in zip(keys, keys[1:]):
        if t <= t1:
            return v0 + (v1 - v0) * (t - t0) / (t1 - t0)
    return keys[-1][1]


def flat(pose: tuple, side: float, height: float = 1.0) -> tuple:
    """A pose for a bone standing up, squashed across the picture and up it but not toward the viewer (as
    build_abbot.flat: squashing her toward you would bring her forward, and from 12 degrees up, lower)."""
    return pose[0], pose[1], (side, height, 1.0)


def quiet() -> dict:
    return {**glint(False), **silk(0.0), **spores(0.0), **spray(0.0)}


def idle(t: float) -> dict:
    """She sinks a pixel on her legs and rises again, as in her first two frames; her back swells as she breathes, her
    raised legs feel the air (the right one bending out, as in her third frame), a foot a side shifts, her fangs work
    and the venom on them swells and draws down."""
    w = 2 * math.pi * t
    bob = 0.5 - 0.5 * math.cos(w)  # 0 up, as in her first frame; 1 sunk, as in her second
    return {
        "body": P(z=-0.9 * bob),
        "abdomen": P(size=1 + 0.025 * math.sin(w - 1.2)),
        "head": P(rx=1.2 * math.sin(w - 0.5)),
        **feet(1, out=0.3 * math.sin(w - 0.4), up=0.5 * math.sin(w - 1.0), side="l"),
        **feet(1, out=0.6 - 0.6 * math.cos(w - 0.5), up=0.3 * math.sin(w - 1.6), side="r"),
        **feet(3, up=0.8 * bump(t, 0.3, 0.16), side="l"),
        **feet(3, up=0.8 * bump(t, 0.8, 0.16), side="r"),
        **jaws(2.5 * math.sin(w - 1.4)),
        **venom(swell=1 + 0.1 * math.sin(w - 2.2), stretch=1 + 0.35 * (0.5 - 0.5 * math.cos(w - 2.2))),
        **quiet(),
    }


REST = idle(0.0)
ENTRANCE, WINDUP, ATTACK = 72, 10, 20
DROP = 50  # how far above the floor she starts, in pixels: out of the frame, line and all


# Her tell, as poses: her front feet lifted off the floor and held up before her (out, up, toward you), her back legs
# raised high and straight (in, up), as far as each can reach.
LIFTED = (0.3, 5.5, 2.0)
RAISED = (-0.5, 2.7)


def rearing(q: float = 0.0) -> dict:
    """Her tell: reared up on her hind legs, her front feet lifted off the floor, her raised back legs lifted higher
    still (she raises them before she strikes), her fangs spread wide, her middle eyes lit white. q (-1 to 1) makes it
    quiver. (The venom is posed apart.)"""
    return {
        "body": P(z=2.6 + 0.15 * q, rx=-4),
        "abdomen": P(size=1.03),
        "head": P(rx=4),
        **feet(4, out=LIFTED[0], up=LIFTED[1] + 0.3 * q, fore=LIFTED[2]),
        **feet(1, out=RAISED[0], up=RAISED[1] + 0.3 * q),
        **jaws(24 + 3 * q),
        **glint(True), **silk(0.0), **spores(0.0), **spray(0.0),
    }


def entrance(t: float) -> dict:
    """The Matriarch arrives. 0-10: she drops from the dark above on her line, faster and faster, legs drawn up under
    her, reaching for the floor at the last. 10: all six feet slam down at once and she squashes onto them, her
    toadstools shaken and puffing spores, her line gone slack. 10-20: she crouches low and still while her line is
    pulled up out of sight. 20-27: she rears up on her hind legs into her tell, her back legs raised high, her fangs
    spread, eyes lit white, venom dripping. 27-44: she holds it, shivering, her raised legs waving and her front feet
    pawing the air in turn, her fangs snapping shut twice. 44-48: stamps her front feet down. 48-68: settles into her
    Idle."""
    f = t * ENTRANCE

    def k(*keys):
        return eased(f, list(keys))

    fall = DROP * (1 - (f / 10) ** 2) if f < 10 else 0.0  # faster and faster, like a dropped thing
    tuck = k((0, 1), (6, 1), (9, 0.35), (10, 0))
    squash = k((0, 1.06), (9.5, 1.06), (10.5, 0.84), (13, 0.97), (16, 1.0))
    sink = k((9.5, 0), (10.5, -1.8), (13, -1.2), (18, -1.2), (24, 0))
    rear = k((20, 0), (27, 1), (44, 1), (47, 0))
    pawing = k((26, 0), (29, 1), (41, 1), (44, 0))
    shiver = math.sin(f * 2.6) * k((27, 0), (29, 1), (43, 1), (45, 0))
    stamp = k((44, 0), (47, 1), (50, 1), (56, 0))  # front feet slammed down a little out from where they stand
    wave = k((27, 0), (30, 1), (40, 1), (44, 0))  # her raised back legs waving, in turn
    clack = k((31, 0), (32.5, 1), (34, 0), (36, 0), (37.5, 1), (39, 0))  # her fangs snapped shut twice

    pose = blend(REST, rearing(shiver), rear)
    pose.update({
        "root": P(z=fall),
        "body": flat(P(z=sink + (2.6 + 0.15 * shiver) * rear - 0.7 * stamp * (1 - rear), rx=-4 * rear),
                     1 / math.sqrt(squash), squash),
        **feet(2, out=-1.5 * tuck, up=6.5 * tuck),
        **feet(3, out=-1.5 * tuck, up=6.5 * tuck),
        **{name: paw for side, phase in (("l", 0.0), ("r", math.pi))
           for name, paw in feet(4, side=side,
                                  out=-1.5 * tuck + LIFTED[0] * rear + 0.6 * stamp * (1 - rear),
                                  up=6.5 * tuck + (LIFTED[1] + 1.6 * pawing * math.sin(
                                      2 * math.pi * (f - 27) / 8 + phase)) * rear,
                                  fore=LIFTED[2] * rear).items()},
        **{name: w for side, phase in (("l", 0.0), ("r", math.pi))
           for name, w in feet(1, side=side,
                               out=0.8 * tuck + (RAISED[0] + 0.9 * wave * math.sin(
                                   2 * math.pi * (f - 27) / 10 + phase)) * rear,
                               up=1.0 * tuck + (RAISED[1] + 0.3 * shiver + 1.0 * wave * math.cos(
                                   2 * math.pi * (f - 27) / 10 + phase)) * rear).items()},
        **jaws(k((0, -4), (9, -4), (11, 6), (18, 4), (22, 0)) + (24 + 3 * shiver - 30 * clack) * rear),
        **caps(14 * k((10, 1), (20, 0)) if f >= 10 else 0.0, f),
        **glint(24 <= f < 45),
        **silk(1.0 if f < 11 else k((11, 1), (18, 0))),
        **spores(whip(f, [(10, 0), (10.5, 0.7), (13, 1.1), (14.5, 1.25)]) if 10 <= f < 15 else 0.0),
        **spray(0.0),
    })
    if 20 <= f < 47:  # dripping while she rears, eased in and out of how it hangs
        pose.update(blend({b: pose[b] for b in ("drip_l", "drip_r")}, dripping(((f - 20) / 13.5) % 1.0), rear))
    return blend(pose, REST, k((56, 0), (68, 1)))


def windup(t: float) -> dict:
    """The tell, held: reared up and quivering with it, twice a loop, venom dripping from her spread fangs."""
    return {**rearing(math.sin(4 * math.pi * t)), **dripping(t)}


COCK = (5.9, 16.0)  # her right front foot drawn up and back over her right side: out and up from where it stands
STAB = (10.2, 0.4)  # and where it strikes: well out past her other feet, just above the floor


def attack(t: float) -> dict:
    """0-4: rears up into her tell (the Windup's pose). 4-6: draws her right front leg (on the viewer's right) up and
    back over her side, leaning away, fangs wide. 6-8: lunges to the right and down, stabbing the leg down to the floor
    well out past her other feet, her fangs snapping shut. 8: the blow lands, venom spraying from her fangs. 8-11:
    holds it. 11-15: pulls back, and settles into Idle's first pose by 18."""
    f = t * ATTACK

    def k(*keys):
        return eased(f, list(keys))

    def struck(*keys):  # drawn back by 6, then struck hard
        return whip(f, list(keys)) if 6 <= f <= 8 else k(*keys)

    up = k((0, 0), (4, 1), (11, 1), (15, 0))
    lean = struck((0, 0), (4, 0), (6, -5), (8, 9), (11, 8), (15, 0))
    pose = blend(REST, rearing(0.0), up)
    pose.update({
        "body": P(x=struck((0, 0), (4, 0), (6, -0.8), (8, 2.8), (11, 2.5), (15, 0)),
                  z=struck((0, 0), (4, 2.6), (6, 3.2), (8, -1.2), (11, -1.0), (15, 0)),
                  rx=-4 * k((0, 0), (4, 1), (6, 1), (8, 0)), ry=lean),
        "head": P(rx=4 * k((0, 0), (4, 1), (6, 1), (8, 0)), ry=-0.9 * lean),  # her face kept level
        **feet(4, side="r", out=struck((0, 0), (4, LIFTED[0]), (6, COCK[0]), (8, STAB[0]), (11, STAB[0]), (15, 0)),
               up=struck((0, 0), (4, LIFTED[1]), (6, COCK[1]), (8, STAB[1]), (11, STAB[1]), (15, 0)),
               fore=struck((0, 0), (4, LIFTED[2]), (6, 1.0), (8, 0.0), (11, 0.0), (15, 0))),
        **jaws(struck((0, 0), (4, 24), (6, 32), (7.4, 32), (8, -6), (11, -6), (15, 0))),
        **venom(swell=k((0, 1), (4, 1.2), (7.5, 1.2), (8, 0.6), (11, 0.6), (15, 1)),
                stretch=k((0, 1), (4, 1.8), (7.5, 1.9), (8, 1.0), (15, 1))),
        **glint(2 <= f < 12),
        **spray(whip(f, [(7.5, 0), (8, 0.95), (11, 1.6)]) if 7.5 <= f < 11.5 else 0.0),
    })
    return blend(pose, REST, max(k((0, 1), (1, 0)), k((14, 0), (18, 1))))


CLIPS = {"Entrance": (entrance, ENTRANCE, False), "Idle": (idle, 24, True), "Windup": (windup, WINDUP, True),
         "Attack": (attack, ATTACK, False)}


# -- building and rendering ---------------------------------------------------------------------------------------

def plant(rig) -> dict:
    """IK on every leg: its tarsus reaches for its foot, three bones up, the knee toward its pole. Each pole's angle is
    found by trying them, so a leg stands just as it was built while nothing moves it."""
    angles = {}
    for n in LEGS:
        for side in "lr":
            leg = f"{n}{side}"
            ik = rig.pose.bones[f"tarsus_{leg}"].constraints.new("IK")
            ik.target, ik.subtarget = rig, f"foot_{leg}"
            ik.pole_target, ik.pole_subtarget = rig, f"pole_{leg}"
            ik.chain_count, ik.use_tail, ik.use_stretch = 3, True, False
            rest = [rig.data.bones[f"{b}_{leg}"].tail_local.copy() for b in ("femur", "tibia")]

            def error(a, ik=ik, leg=leg, rest=rest):
                ik.pole_angle = math.radians(a)
                bpy.context.view_layer.update()
                return sum((rig.pose.bones[f"{b}_{leg}"].tail - r).length for b, r in zip(("femur", "tibia"), rest))

            best = min(range(-180, 180, 10), key=error)
            best = min((best + d / 2 for d in range(-20, 21)), key=error)
            angles[leg] = (best, round(error(best) / kit.S, 3))  # the knee and joint's error, in pixels
    return angles


def build() -> dict:
    scene = bpy.context.scene
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
    scene.name = SCENE
    scene.render.fps = kit.FPS
    scene.frame_start, scene.frame_end = 0, ENTRANCE
    body, n_verts, n_faces, palette = build_model(scene, MESH)
    rig = build_rig(scene, MESH, body)
    # Her legs keep their size whatever her body does (it squashes as she lands).
    for bone in rig.data.bones:
        if bone.name.startswith("femur_"):
            bone.inherit_scale = "NONE"
    angles = plant(rig)
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
    glb = OUT / "sporefang_matriarch.glb"
    bpy.ops.export_scene.gltf(
        filepath=str(glb), export_format="GLB", use_active_scene=True,
        export_animations=True, export_animation_mode="ACTIONS", export_force_sampling=True,
        export_frame_range=False, export_anim_slide_to_zero=False, export_reset_pose_bones=True,
        export_skins=True, export_def_bones=False, export_yup=True, export_apply=False,
    )
    blend_file = OUT / "sporefang_matriarch.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_file))
    return {"verts": n_verts, "faces": n_faces, "colours": palette, "bones": len(rig.data.bones),
            "clips": [a.name for a in actions], "poles": angles, "glb_bytes": glb.stat().st_size}


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
    """A few frames of a clip, to check the poses: sporefang_matriarch/test/<clip>_<frame>.png."""
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
