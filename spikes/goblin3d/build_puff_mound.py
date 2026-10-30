"""Spike: the Puff Mound rigged, animated and rendered in Blender, the way build_abbot.py did the Drowned Abbot, from the
front.

Reads the model inflate_puff_mound.py wrote (puff_mound/puff_mound_mesh.json). Runs headless:

    B=/Applications/Blender.app/Contents/MacOS/Blender
    $B -b --factory-startup --python spikes/goblin3d/build_puff_mound.py -- build     # puff_mound/puff_mound.glb + .blend
    $B -b spikes/goblin3d/puff_mound/puff_mound.blend --python spikes/goblin3d/build_puff_mound.py -- frames
    $B -b spikes/goblin3d/puff_mound/puff_mound.blend --python spikes/goblin3d/build_puff_mound.py -- test Attack 0 5 8

Four clips at 24 fps, all framed alike so its base stays on the same spot: Entrance (once; ends on Idle's first pose),
Idle (loops), Windup (loops: its tell, held) and Attack (once; from Idle's first pose back to it). "frames" renders
them from the front into puff_mound/frames_hd/<clip>/0/<frame>.png, 256 pixels a side, toon-shaded in its sprite's
colours, for reduce.py to shrink.

The stage plays clips at 12 frames a second (every other frame of these), and stands a foe in the first and middle
frames of its Idle or Windup by turns: so the moments that matter (the landing, the burst) fall on even frames, and the
Idle's frames 0 and 12, the Windup's 0 and 5, are its two poses there.
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

TAG = kit.TAG = "puff_mound"  # the King's helpers name and find what they make by it
kit.GROUND = 23  # its base sits a pixel lower in its sprite than the King's boots: the floor is under it, framed the same
OUT = HERE / "puff_mound"
SCENE = "PuffMound"
SPAN, ELEVATION = 48, 12  # as every boss was framed
MESH = json.loads((OUT / "puff_mound_mesh.json").read_text())
NEST = tuple(MESH["nest"])
SPORES = sorted(int(b.split("_")[1]) for b in MESH["bones"] if b.startswith("spore_"))
LOBES = sorted(int(b.split("_")[1]) for b in MESH["bones"] if b.startswith("lobe_"))


# -- poses ------------------------------------------------------------------------------------------------------------
# As in build_king.py: turns in degrees about the rig's axes (x to the viewer's right, y away, z up), nudges in pixels,
# a squash. Its body is squashed (sq below 1: low and wide) and swollen (size) about a pivot a pixel above the floor,
# its base staying put; its top (its cap) can lean on it (positive tips it toward the viewer's right). Spores and the
# cloud's lobes are put where they're wanted in the sprite's own pixels (x right, y down, depth toward the viewer).

def shape(sq: float = 1.0, size: float = 1.0, lean: float = 0.0, x: float = 0.0, deep: float | None = None) -> tuple:
    """A pose for the body or the top: squashed or stretched, swollen, leaned, nudged sideways. Its depth goes with its
    width unless `deep` says otherwise."""
    wide = 1 / math.sqrt(sq)
    return (0.0, lean, 0.0), (x, 0.0, 0.0), (wide * size, sq * size, (wide if deep is None else deep) * size)


def eyes(opened: float = 1.0, wide: float = 1.0, squash: float = 1.0) -> dict:
    """Its eyes: 1 open, 0.8 squeezed (no thinner, or they're lost small), `wide` stretching them across. `squash` is
    its body's: squashed flat, the eyes ride it but keep their height, so they don't go thin and vanish."""
    s = (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (wide, max(opened, 0.05) / min(squash, 1.0), 1.0)
    return {"eye_l": s, "eye_r": s}


def mouth(opened: float) -> dict:
    """0 shut (and gone, as in its sprite), 1 wide open."""
    o = min(max(opened, 0.0), 1.2)
    if o < 0.04:
        return {"mouth": P(size=0.01)}
    return {"mouth": ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.55 + 0.45 * min(o, 1.0), o, 1.0))}


def put(bone: str, x: float, y: float, z: float = 0.0, size: float = 1.0) -> dict:
    """A spore or a lobe at (x, y, depth), grown to `size` (0 hides it)."""
    nx, ny, nz = NEST
    return {bone: P(x=x - nx, y=-(z - nz), z=ny - y, size=max(size, 0.01))}


# The two spores that drift up off it as it stands: each born inside its cap a share of the way through the loop, and
# going off up to one side, so that one of them is up in the air, clear of its cap, in each of the two frames the
# stage stands it in, half way through its life. There it's `out` pixels to the side and 7 above its cap's top: a
# place where it's one pixel at 40 and at 48 both, a dot, as its sprite draws them.
DRIFTERS = [(1, 0.5, -1, 4.41), (2, 0.0, 1, 4.59)]


def drifting(t: float, born: float, side: int, out: float) -> tuple:
    """(x, y, depth, size) of a drifting spore, t of the way through the Idle."""
    u = (t - born) % 1.0
    x = 12 + side * (1.0 + (out - 0.717) * (u / 0.5) ** 0.8 + 0.35 * math.sin(2 * math.pi * 1.3 * u))
    size = eased(u, [(0.0, 0.3), (0.12, 1.0), (0.84, 1.0), (0.95, 0.01)])
    return x, 8.4 - 15.81 * u ** 0.75, 0.6, size


def hidden() -> dict:
    """Every spore and lobe out of sight: the drifters inside its cap where they're born, the rest in the nest."""
    pose = {f"spore_{n}": P(size=0.01) for n in SPORES}
    pose.update({f"lobe_{n}": P(size=0.01) for n in LOBES})
    for n, born, side, out in DRIFTERS:
        x, y, z, _ = drifting(born, born, side, out)
        pose.update(put(f"spore_{n}", x, y, z, 0.0))
    return pose


def idle(t: float) -> dict:
    """Wheezing: it breathes in slow, swelling up and out (a pixel or two at 48, as its sprite's two frames do), its
    face rising from the middle of one pixel to the middle of the next, and out with a wheeze, its mouth opening a
    little, a spore drifting up off its cap on each breath."""
    w = 2 * math.pi * t
    breath = 0.5 - 0.5 * math.cos(w)  # 0 out (frame 0), 1 in (frame 12)
    wheeze = max(0.0, -math.sin(w)) ** 2  # the out-breath
    pose = {
        **hidden(),
        "body": shape(sq=1 + 0.045 * breath, size=1 + 0.045 * breath),
        "top": shape(sq=1 + 0.015 * breath),
        **eyes(),
        **mouth(0.6 * wheeze),
    }
    for n, born, side, out in DRIFTERS:
        pose.update(put(f"spore_{n}", *drifting(t, born, side, out)))
    return pose


REST = idle(0.0)
ENTRANCE, WINDUP, ATTACK = 64, 10, 22


def arc(f: float, start: float, at: tuple, reach: float, high: float, peak: float, gone: float,
        drift: float = 0.0, out: float = 4.0) -> tuple:
    """(x, y, size) of a spore thrown from `at` at frame `start`: out sideways by `reach` (slowing as it goes, there by
    `out` frames after its peak), up by `high` at frame start + peak and down again as a thing thrown falls, then on
    sideways by `drift` a frame, till it's `gone` (shrinking away over two frames)."""
    tau = f - start
    if tau < 0:
        return at[0], at[1], 0.0
    u = min(tau / (peak + out), 1.0)
    x = at[0] + reach * (1 - (1 - u) ** 2) + drift * max(tau - peak - out, 0.0)
    y = at[1] - high * (1 - ((tau - peak) / peak) ** 2)
    size = eased(f, [(start, 0.5), (start + 1, 1.0), (gone - 2, 1.0), (gone, 0.0)])
    return x, y, size


def flung(f: float, start: float, at: tuple, to: tuple, gone: float, drift: tuple = (0.0, 0.0),
          arrive: float = 4.0) -> tuple:
    """(x, y, size) of a spore shot from `at` at frame `start`: fast, then slowing, reaching `to` `arrive` frames on,
    then drifting by `drift` a frame till it's `gone`."""
    if f < start:
        return at[0], at[1], 0.0
    u = min((f - start) / arrive, 1.0)
    ease = 1 - (1 - u) ** 3
    after = max(f - start - arrive, 0.0)
    x = at[0] + (to[0] - at[0]) * ease + drift[0] * after
    y = at[1] + (to[1] - at[1]) * ease + drift[1] * after
    size = eased(f, [(start, 0.6), (start + 1, 1.0), (gone - 2, 1.0), (gone, 0.0)])
    return x, y, size


# The puff when it lands: three spores each way, thrown out from under it in arcs, low and far, higher, higher still,
# landing again out to its side: (reach, how high, frames to the top of the arc).
SPLASH = [(11.5, 1.8, 3.5), (11.0, 5.0, 4.5), (10.0, 8.5, 5.5)]
# Its fountain, showing off: seven spores out of its top, up and over both ways: (reach, how high, frames to the top,
# frame it's gone).
FOUNTAIN = [(-10.5, 7.5, 5.0, 53), (-7.0, 11.0, 6.0, 57), (-3.6, 13.5, 6.5, 55), (0.4, 15.0, 7.0, 58),
            (3.9, 12.5, 6.5, 54), (7.4, 10.5, 5.5, 56), (10.6, 7.0, 5.0, 55)]


def entrance(t: float) -> dict:
    """The Puff Mound arrives. 0-9: it drops in from above, stretched long, its mouth an O. 10: it lands (an even
    frame: the stage shows it), squashed flat, and a puff of its spores splashes out from under it both ways. 12-20:
    it springs up in a hop and comes down again, 20-29 wobbling like a jelly. 30-42: it breathes in, deeper and
    deeper, swelling up proud, its eyes squeezed shut. 43-48: PFFF: it lets it all out of its top in a fountain of
    glittering spores, deflating with a shudder. 48-56: the spores spill away as it bounces back, and 56-63 it settles
    into its Idle."""
    f = t * ENTRANCE

    def k(*keys):
        return eased(f, list(keys))

    fall = 46 * (1 - (f / 10) ** 2) if f < 10 else 0.0  # faster and faster, like a dropped thing
    hop = 5.0 * (1 - ((f - 17) / 3) ** 2) if 14 <= f <= 20 else 0.0
    shudder = math.cos(math.pi * f) * k((43, 0), (44, 1), (47, 1), (49, 0))  # every other frame, one way and the other
    sq = k((0, 1.2), (9, 1.2), (10, 0.62), (11.5, 0.6), (13.2, 1.14), (15, 1.06), (17, 1.0), (19, 1.05), (20, 0.8),
           (21.2, 0.84), (23, 1.07), (25.5, 0.96), (27.5, 1.02), (29, 1.0), (38, 1.06), (42, 1.06), (44, 0.9),
           (47, 0.95), (50, 1.04), (53, 0.98), (55, 1.0))
    pose = {
        **hidden(),
        "root": P(z=fall + hop),
        "body": shape(sq=sq,
                      size=k((29, 1.0), (38, 1.17), (42, 1.18), (43, 1.14), (47, 0.95), (50, 1.01), (53, 1.0)),
                      x=0.3 * shudder),
        "top": shape(lean=k((20, 0), (22, 7), (24.5, -5), (27, 3), (29.5, -1.5), (31, 0)) + 3 * shudder
                     + 1.2 * math.cos(math.pi * f) * k((38, 0), (39, 1), (42, 1), (43, 0))),
        **eyes(k((0, 1.15), (9, 1.15), (10, 0.8), (12, 0.85), (14, 1.0), (30, 1.0), (35, 0.8), (42, 0.8),
                 (43.5, 1.25), (48, 1.1), (51, 1.0)),
               k((0, 0.9), (9, 0.9), (10, 1.35), (13, 1.0), (30, 1.0), (35, 1.45), (42, 1.45), (43.5, 1.3), (48, 1.05),
                 (51, 1.0)),
               squash=sq),
        **mouth(k((0, 0.75), (9, 0.75), (10, 0.0), (42, 0.0), (43, 1.0), (46.5, 0.9), (49.5, 0.0))),
    }
    for n, (reach, high, peak) in zip((3, 4, 5), SPLASH):
        for bone, side in ((n, -1), (n + 3, 1)):
            x, y, size = arc(f, 10, (12 + side * 5.0, 21.0), side * reach, high, peak, 10 + 2 * peak,
                             drift=side * 0.1, out=1.5)
            pose.update(put(f"spore_{bone}", x, y, 1.2, size))
    if f >= 42:
        for n, (reach, high, peak, gone) in zip(range(3, 10), FOUNTAIN):
            x, y, size = arc(f, 43 + 0.3 * (n % 3), (12 + 0.2 * reach, 7.0), reach, high, peak, gone,
                             drift=0.03 * reach)
            pose.update(put(f"spore_{n}", x, y, 0.8, size))
    return blend(pose, REST, k((56, 0), (63, 1)))


def swollen(pulse: float = 0.0, shiver: float = 0.0) -> dict:
    """Its tell: swollen up and up, taut, its eyes squeezed shut with the strain. pulse (0 to 1) swells it further;
    shiver (-1 to 1) shakes it, its skin squeaking."""
    return {
        **hidden(),
        "body": shape(sq=1.04 + 0.05 * pulse, size=1.16 + 0.12 * pulse, x=0.4 * shiver),
        "top": shape(size=1.0 + 0.02 * pulse, lean=1.2 * shiver),
        **eyes(0.72, 1.25),
        **mouth(0.0),
    }


def windup(t: float) -> dict:
    """The tell, held: swollen, and swelling further and shivering by turns, so its two frames on the stage (0 and
    the middle) are one swollen and one more so, shaken the other way."""
    w = 2 * math.pi * t
    return swollen(pulse=0.5 - 0.5 * math.cos(w), shiver=math.cos(5 * w))


# The cloud it bursts out of its top, up and away to the viewer's left, a heap of round lobes with a flat-ish bottom:
# where the cloud's middle is, frame by frame, and how far its lobes spread as it billows; each lobe's place in it, how
# big it grows and the frame it starts to thin away (so the cloud breaks up into puffs, then nothing).
CLOUD = [(8, (2.8, 6.4)), (10, (0.4, 3.6)), (12, (-1.4, 2.0)), (15, (-1.6, 0.0)), (19, (-2.0, -2.5))]
SPREAD = [(8, 0.9), (10, 1.0), (12, 1.12), (15, 1.22), (19, 1.35)]
PUFFS = [(1, (0.0, 0.5), 3.0, 16), (2, (-3.2, 1.0), 2.5, 15), (3, (3.0, 1.2), 2.3, 14), (4, (-1.5, -2.2), 2.5, 16),
         (5, (1.8, -1.8), 2.2, 15), (6, (-5.2, 1.6), 1.8, 14)]
# The glittering specks shot out of it, round it and past it: where each gets to, and the frame it's gone.
SPECKS = [(3, (-8.6, 13.4), 16), (4, (-4.4, 11.0), 18), (5, (-8.6, 7.6), 17), (6, (-3.8, -6.6), 19),
          (7, (2.4, -7.6), 18), (8, (7.8, -4.6), 17), (9, (-6.8, 16.6), 16), (10, (-8.0, -2.2), 19)]


def attack(t: float) -> dict:
    """PFFF. 0-5: it breathes in hard (sucking its drifting spore back in) and swells up taut (its Windup). 5-7: holds
    it, shivering. 8: it squashes down and bursts a cloud of spores out of its top, up and away to the viewer's left,
    its mouth wide, glittering specks flying: the blow lands (an even frame: the stage shows it). 8-14: the cloud
    billows up and away while it sits squashed, leaning back from it. 14-22: it springs back up and wobbles into its
    Idle as the cloud thins away to nothing."""
    f = t * ATTACK

    def k(*keys):
        return eased(f, list(keys))

    shiver = math.cos(math.pi * f) * k((4, 0), (5, 1), (7, 1), (7.5, 0))
    sq = k((0, 1.0), (5, 1.07), (7, 1.08), (8, 0.68), (10, 0.7), (12, 0.86), (13.5, 1.08), (16, 0.96), (18.5, 1.01),
           (20, 1.0))
    pose = {
        **hidden(),
        "body": shape(sq=sq,
                      size=k((0, 1.0), (5, 1.2), (7, 1.21), (8, 1.04), (10, 0.96), (13, 0.98), (16, 1.0)),
                      lean=k((7, 0), (8, 6), (11, 5), (13.5, -3), (16, 1), (18, 0)), x=0.4 * shiver),
        "top": shape(lean=1.2 * shiver + k((12, 0), (14, -2), (16.5, 1.5), (19, 0))),
        **eyes(k((0, 1.0), (4, 0.8), (7, 0.8), (7.8, 1.25), (11, 1.15), (14, 1.0)),
               k((0, 1.0), (4, 1.45), (7, 1.45), (7.8, 1.3), (11, 1.2), (14, 1.0)), squash=sq),
        **mouth(k((7, 0.0), (8, 1.0), (11, 1.0), (14.5, 0.0))),
    }
    if f >= 7.5:
        cx, cy = eased(f, [(t0, p[0]) for t0, p in CLOUD]), eased(f, [(t0, p[1]) for t0, p in CLOUD])
        spread = eased(f, SPREAD)
        for n, (dx, dy), big, thin in PUFFS:
            grow = eased(f, [(7.5, 0.4), (8, 0.95), (10, 1.0), (thin, 0.95), (thin + 3, 0.0)])
            pose.update(put(f"lobe_{n}", cx + spread * dx, cy + spread * dy, 0.5, big * grow))
        for n, to, gone in SPECKS:
            x, y, size = flung(f, 8, (3.0, 8.0), to, gone, drift=(-0.03, -0.12), arrive=4)
            pose.update(put(f"spore_{n}", x, y, 1.0, size))
    return blend(pose, REST, max(k((0, 1), (1.5, 0)), k((16, 0), (21.5, 1))))


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
    glb = OUT / "puff_mound.glb"
    bpy.ops.export_scene.gltf(
        filepath=str(glb), export_format="GLB", use_active_scene=True,
        export_animations=True, export_animation_mode="ACTIONS", export_force_sampling=True,
        export_frame_range=False, export_anim_slide_to_zero=False, export_reset_pose_bones=True,
        export_skins=True, export_def_bones=False, export_yup=True, export_apply=False,
    )
    blend_file = OUT / "puff_mound.blend"
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
    """A few frames of a clip, to check the poses: puff_mound/test/<clip>_<frame>.png."""
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
