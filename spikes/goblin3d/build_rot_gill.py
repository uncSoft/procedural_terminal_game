"""Spike: the Rot Gill rigged, animated and rendered in Blender, the way build_thornmother.py did the Thornmother, from
the front.

Reads the model inflate_rot_gill.py wrote (rot_gill/rot_gill_mesh.json). Runs headless:

    B=/Applications/Blender.app/Contents/MacOS/Blender
    $B -b --factory-startup --python spikes/goblin3d/build_rot_gill.py -- build      # rot_gill/rot_gill.glb + .blend
    $B -b spikes/goblin3d/rot_gill/rot_gill.blend --python spikes/goblin3d/build_rot_gill.py -- frames
    $B -b spikes/goblin3d/rot_gill/rot_gill.blend --python spikes/goblin3d/build_rot_gill.py -- test Attack 0 5 8

Four clips at 24 fps, all framed alike so its stalk stays on the same spot: Entrance (once; ends on Idle's first pose),
Idle (loops), Windup (loops: its tell, held) and Attack (once; from Idle's first pose back to it). "frames" renders
them from the front into rot_gill/frames_hd/<clip>/0/<frame>.png, 256 pixels a side, toon-shaded in its sprite's
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

TAG = kit.TAG = "rot_gill"  # the King's helpers name and find what they make by it
kit.GROUND = 23  # its stalk ends a pixel lower in its sprite than the King's boots: the floor's under it, framed alike
OUT = HERE / "rot_gill"
SCENE = "RotGill"
SPAN, ELEVATION = 48, 12  # as every boss was framed
MESH = json.loads((OUT / "rot_gill_mesh.json").read_text())

N = MESH["gills"]
PHI = [2 * math.pi * k / N for k in range(N)]  # which way each gill faces: 0 the viewer, then round to their right
GILLS = [f"gill_{k:02d}" for k in range(N)]
FRONT = [k for k in range(N) if math.cos(PHI[k]) > 0.75]  # the gills behind its mouth
FOOT = MESH["bones"]["gill_00"]["head"][1]  # where the gills' feet are, and the top of its mouth (pixels down)
MOUTH_TOP = MESH["bones"]["jaw"]["head"][1]
FLESH = 8.4 * MESH["scale"]  # the flesh's half-width under the gills
EQUATOR = FOOT - MESH["bones"]["flesh"]["head"][1]  # how far its widest is above the gills' feet


# -- poses ------------------------------------------------------------------------------------------------------------
# As in build_king.py: turns in degrees about the rig's axes (x to the viewer's right, y away, z up), nudges in pixels,
# a squash. A positive turn about y tips the top of a part toward the viewer's right; a positive turn about z turns its
# face toward the viewer's right.

PUSH, TILT, NARROW, RISE = 0.85, 13.0, 0.5, 0.06  # a gill opened all the way: pushed out, tipped out, narrowed, taller
FAN = 0.3  # opened all the way, the lime gills tip out further than the green ones, so its edge frills


def gill(k: int, push: float = 0.0, tilt: float = 0.0, gap: float = 0.0, rise: float = 0.0) -> tuple:
    """Gill k opened: pushed out off the flesh (push, of PUSH), its top tipped out about its foot (tilt, of TILT),
    narrowed to show the pink flesh between it and the next (gap, of NARROW; the ones facing the viewer most), and
    stretched taller (rise, of RISE)."""
    phi = PHI[k]
    turn = Quaternion(Vector((math.cos(phi), math.sin(phi), 0.0)), math.radians(TILT * tilt)).to_euler("YXZ")
    narrow = 1 - NARROW * gap * (0.35 + 0.65 * abs(math.cos(phi)))
    return ((math.degrees(turn.x), math.degrees(turn.y), math.degrees(turn.z)),
            (PUSH * push * math.sin(phi), -PUSH * push * math.cos(phi), 0.0),
            (narrow, 1 + RISE * rise, 1.0))  # its bone's x runs across it, y up it, z out


def opened(a: float, k: int = 0) -> dict:
    """A gill opened by a (0 shut, 1 open), as its tell opens them: every way at once, fanned in turn."""
    return dict(push=a, tilt=a * (1 + FAN * (1 if k % 2 == 0 else -1)), gap=a, rise=a)


def rippled(a: float) -> dict:
    """A gill lifted by a ripple running round them: pushed out, hardly tipped, not parted."""
    return dict(push=a, tilt=0.15 * a)


def forward(push: float, tilt: float) -> float:
    """How far its face must come forward to stay in front of the gills behind it when they're pushed and tipped out."""
    return PUSH * push + (FOOT - MOUTH_TOP) * math.sin(math.radians(TILT * tilt)) + 0.1 * push


def gills(a: float = 0.0, each=None) -> dict:
    """Every gill opened by a, or each as each(k) says (opened() or rippled()); its flesh swelling out into the room
    they leave, as far as the one that's moved out least (further and it would show through it), so no sky shows
    between them and it at its sides; and its face brought forward to stay in front of the ones behind it."""
    amounts = [each(k) if each else opened(a, k) for k in range(N)]
    out = max(forward(amounts[k].get("push", 0.0), amounts[k].get("tilt", 0.0)) for k in FRONT)
    least = min(PUSH * g.get("push", 0.0) + EQUATOR * math.sin(math.radians(TILT * g.get("tilt", 0.0)))
                for g in amounts)
    swell = PUSH * sum(g.get("push", 0.0) for g in amounts) / N
    return {**{GILLS[k]: gill(k, **amounts[k]) for k in range(N)},
            "flesh": P(sq=1 + 0.5 * swell / FLESH, wide=1 + least / FLESH),
            "face": P(y=-out)}


def mouth(gape: float) -> dict:
    """0 shut, as drawn; 1 wide open: stretched down from its top, its throat showing."""
    o = max(gape, 0.0)
    return {"jaw": P(sq=1 + 0.42 * o, wide=1 + 0.05 * o), "throat": P(size=max(min(1.4 * o - 0.25, 1.0), 0.02))}


def drips(left: float = 1.0, right: float = 1.0, lean: float = 0.0) -> dict:
    """Its drips stretched so long (1: as made), hanging straight down whatever its body does (lean: how far it's tipped
    its top toward the viewer's right)."""
    return {"drip_l": P(ry=-lean, sq=left, wide=1.0), "drip_r": P(ry=-lean, sq=right, wide=1.0)}


def poison(glob: tuple | None = None, splat: float = 0.0, landing: float = 0.0) -> dict:
    """The glob (its pose: where it's got to and its shape), the splat it makes, and the drops thrown up when it lands:
    hidden when None (or 0)."""
    return {"glob": glob or P(size=0.02), "splat": P(size=max(splat, 0.02)),
            "splash_l": P(size=max(landing, 0.02)), "splash_r": P(size=max(landing, 0.02))}


def flat(sq: float = 1.0, wide: float | None = None, z: float = 0.0) -> tuple:
    """The root squashed (sq below 1 squat and wide) across the picture and up it but not toward the viewer: its foot
    brought forward would look lower from a little above, and sink below the floor."""
    return (0.0, 0.0, 0.0), (0.0, 0.0, z), (1 / math.sqrt(sq) if wide is None else wide, sq, 1.0)


def whip(t: float, keys: list) -> float:
    """A value running straight between (time, value) keys, without easing: for things thrown hard."""
    if t <= keys[0][0]:
        return keys[0][1]
    for (t0, v0), (t1, v1) in zip(keys, keys[1:]):
        if t <= t1:
            return v0 + (v1 - v0) * (t - t0) / (t1 - t0)
    return keys[-1][1]


RIPPLE = 0.5  # how far its gills open as a ripple runs round them, idling


def idle(t: float) -> dict:
    """It breathes, its ball sinking a little on its stalk and rising; a ripple runs round its gills, twice round a
    loop; its mouth works, and its drips stretch slowly, each in turn, till a drop falls and it starts again."""
    w = 2 * math.pi * t
    sink = 0.5 - 0.5 * math.cos(w)
    return {
        "body": P(sq=1 - 0.055 * sink, wide=1 + 0.025 * sink),  # the ball, not its stalk: its foot stays still
        **gills(each=lambda k: rippled(RIPPLE * (0.5 + 0.5 * math.sin(w - 2 * PHI[k])))),
        **mouth(0.1 + 0.22 * sink),
        **drips(1 + 0.35 * ((t + 0.5) % 1.0) ** 2, 1 + 0.4 * t ** 2),
        **poison(),
    }


REST = idle(0.0)
ENTRANCE, WINDUP, ATTACK = 72, 10, 20


def entrance(t: float) -> dict:
    """The Rot Gill arrives. 0-10: it drops from the roof, gills shut tight, its drips pulled up short. 10: its stalk
    hits the floor; it squashes flat, its gills burst open with the shock and drops of poison fly up. 10-24: it wobbles
    back up like a jelly. 22-37: it turns its mouth one way, then the other: who's there? 37-45: it rises tall on its
    stalk, ripples running round its gills. 45-52: it opens every gill at once, mouth agape and shivering. 52-60: shuts
    them and sinks back into its Idle."""
    f = t * ENTRANCE

    def k(*keys):
        return eased(f, list(keys))

    fall = 46 * (1 - (f / 10) ** 2) if f < 10 else 0.0  # faster and faster, like a dropped thing
    squash = k((0, 1.12), (9.6, 1.12), (10.6, 0.7), (12.6, 1.14), (15, 0.9), (18, 1.05), (21, 0.98), (24, 1.0),
               (37, 1.0), (43, 1.07), (52, 1.07), (57, 0.97), (60, 1.0))
    rippling = k((36, 0), (39, 1), (44, 1), (46, 0))
    show = k((44, 0), (46, 1), (51, 1), (55, 0))
    shake = math.sin(f * 2.6) * show
    shock = k((9.8, 0), (10.8, 0.8), (13, 0.15), (15, 0.35), (19, 0))
    wave = 2 * math.pi * (f - 36) / 8

    def opening(g):
        ripple = rippled(0.6 * max(0.0, math.sin(wave - PHI[g])) ** 2 * rippling)
        whole = opened(max(shock, show * (1 + 0.1 * shake * (1 if g % 2 else -1))), g)
        return {key: max(ripple.get(key, 0.0), value) for key, value in whole.items()}

    pose = {
        "root": flat(squash, z=fall),
        "body": P(rz=k((22, 0), (25.5, -26), (28.5, -26), (32, 24), (35, 24), (38, 0)), x=0.15 * shake),
        **gills(each=opening),
        **mouth(k((0, 0.5), (9, 0.5), (11, 0), (24, 0), (26, 0.3), (36, 0.2), (45, 0.4), (47, 1.0), (51, 1.0),
                  (55, 0.1)) + 0.08 * shake),
        # Pulled up short as it falls and as it lands, flung long as it springs back up, settling.
        **drips(k((0, 0.45), (11, 0.45), (13, 1.35), (15.5, 0.85), (18, 1.1), (21, 1.0), (45, 1.0), (48, 1.3),
                  (51, 1.3), (55, 1.0)),
                k((0, 0.45), (11, 0.45), (13.5, 1.3), (16, 0.9), (18.5, 1.08), (21, 1.0), (45, 1.0), (48, 1.25),
                  (51, 1.25), (55, 1.0))),
        **poison(landing=whip(f, [(10, 0), (10.5, 0.8), (13, 1.2), (14, 1.3)]) if 10 <= f < 14.5 else 0.0),
    }
    return blend(pose, REST, k((57, 0), (64, 1)))


def flared(q: float = 0.0) -> dict:
    """Its tell: every gill opened at once, the pink flesh showing between them; puffed up and risen on its stalk,
    mouth agape, drips stretched; shivering with it (q, -1 to 1), its gills in turn."""
    return {
        "root": flat(1.05, 1.0),
        "body": P(size=1.04, x=0.12 * q),
        **gills(each=lambda g: opened(1.0 + 0.1 * q * (1 if g % 2 else -1), g)),
        **mouth(0.8 + 0.1 * q),
        **drips(1.25 + 0.05 * q, 1.35 - 0.05 * q),
        **poison(),
    }


def windup(t: float) -> dict:
    """The tell, held, shivering, twice a loop."""
    return flared(math.sin(4 * math.pi * t))


GLOB = MESH["bones"]["glob"]["head"]
SPLAT = MESH["bones"]["splat"]["head"]
BODY = MESH["bones"]["body"]["head"]
LAUNCH, HIT = 5.0, 8.0  # frames: the glob leaves its mouth, and bursts on whatever it hits
OPENED = ((0, 0), (2.5, 1), (4.2, 1), (5.6, 0.12), (9, 0.05), (12, 0))  # its gills: open, slammed shut to spit
LEAN = ((0, 0), (3, -11), (4, -12), (5.5, 14), (8, 17), (11, 13), (15, 0))  # its top tipped to the viewer's right
SHOVE = ((0, 0), (3, -0.8), (5.5, 1.1), (8, 1.3), (11, 1.0), (15, 0))  # and its body pushed that way, in pixels


def attack(t: float) -> dict:
    """It spits. 0-3: opens every gill (Windup's pose) and rears back to the viewer's left, mouth agape. 4-5.5: slams
    them shut, snapping its top over to the viewer's right, and spits: the glob leaves its mouth on 5. 5-8: the glob
    flies out to the right. 8: it bursts on whatever it hits, in a splat of poison. 8-12: it holds. 12-18: back to
    Idle's first pose."""
    f = t * ATTACK

    def k(*keys):
        return eased(f, list(keys))

    spread, lean, shove = k(*OPENED), k(*LEAN), k(*SHOVE)
    pose = {
        "root": flat(k((0, 1), (3, 1.05), (5, 0.96), (7, 0.98), (12, 1.0)), 1.0),
        "body": P(ry=lean, x=shove, size=1 + 0.04 * spread),
        **gills(spread),
        **mouth(k((0, 0.1), (2.5, 0.8), (4.2, 1.0), (5, 1.15), (6.5, 0.55), (9, 0.3), (14, 0.1))),
        **drips(k((0, 1), (3, 1.25), (5, 0.6), (8, 1.3), (12, 1.0)),
                k((0, 1), (3, 1.3), (5, 0.6), (8, 1.35), (12, 1.0)), lean=lean),
    }
    glob = None
    if LAUNCH - 0.5 <= f < HIT + 0.5:
        # Out of its mouth, where that is when it spits (its top tipped over, shoved along and brought forward with its
        # gills), out to the right, slowing as it goes, in a low arc; on 8 it smacks flat into whatever it hits.
        h = BODY[1] - GLOB[1]
        lean_at = math.radians(eased(LAUNCH, list(LEAN)))
        start = (h * math.sin(lean_at) + eased(LAUNCH, list(SHOVE)), h * (math.cos(lean_at) - 1),
                 forward(eased(LAUNCH, list(OPENED)), (1 + FAN) * eased(LAUNCH, list(OPENED))) + 1.6)
        end = (SPLAT[0] - GLOB[0], GLOB[1] - SPLAT[1], SPLAT[2] - GLOB[2])
        u = 1 - (1 - min(max((f - LAUNCH) / (HIT - 0.5 - LAUNCH), 0.0), 1.0)) ** 2
        x, z, depth = (a + (b - a) * u for a, b in zip(start, end))
        smack = min(max((f - (HIT - 0.6)) / 0.6, 0.0), 1.0)
        glob = ((0.0, 0.0, 0.0), (x + 0.5 * smack, -depth, z + 1.2 * math.sin(math.pi * u)),
                (1 - 0.55 * smack, 1 + 0.5 * smack, 1.0))
    pose.update(poison(glob=glob, splat=k((HIT - 0.5, 0), (HIT, 0.85), (12, 1.35)) if HIT - 0.5 <= f < 12.5 else 0.0))
    return blend(pose, REST, max(k((0, 1), (1, 0)), k((14, 0), (18, 1))))


CLIPS = {"Entrance": (entrance, ENTRANCE, False), "Idle": (idle, 24, True), "Windup": (windup, WINDUP, True),
         "Attack": (attack, ATTACK, False)}


# -- building and rendering ---------------------------------------------------------------------------------------

def rig_up(scene, body):
    """The King's rig, with each gill's bone rolled so its x runs across the gill (to narrow it) and its z out, and the
    drips and the poison keeping their own size whatever carries them."""
    rig = build_rig(scene, MESH, body)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    for name, bone in MESH["bones"].items():
        if "z" in bone:
            dx, dy, dz = bone["z"]
            rig.data.edit_bones[name].align_roll(Vector((dx, -dz, -dy)))
    bpy.ops.object.mode_set(mode="OBJECT")
    for name in ("drip_l", "drip_r", "glob", "splat", "splash_l", "splash_r"):
        rig.data.bones[name].inherit_scale = "NONE"
    return rig


def build() -> dict:
    scene = bpy.context.scene
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
    scene.name = SCENE
    scene.render.fps = kit.FPS
    scene.frame_start, scene.frame_end = 0, ENTRANCE
    body, n_verts, n_faces, palette = build_model(scene, MESH)
    rig = rig_up(scene, body)
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
    glb = OUT / "rot_gill.glb"
    bpy.ops.export_scene.gltf(
        filepath=str(glb), export_format="GLB", use_active_scene=True,
        export_animations=True, export_animation_mode="ACTIONS", export_force_sampling=True,
        export_frame_range=False, export_anim_slide_to_zero=False, export_reset_pose_bones=True,
        export_skins=True, export_def_bones=False, export_yup=True, export_apply=False,
    )
    blend_file = OUT / "rot_gill.blend"
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
    """A few frames of a clip, to check the poses: rot_gill/test/<clip>_<frame>.png."""
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
