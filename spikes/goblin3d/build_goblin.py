"""Spike: the voxel goblin built, rigged and animated in Blender, then exported as goblin.glb.

Runs inside Blender (which has no PIL, so it reads the cubes voxelize.py wrote), from the Blender MCP or Blender's
Python console:

    import runpy; runpy.run_path("<repo>/spikes/goblin3d/build_goblin.py")                            # build + export
    import runpy; runpy.run_path("<repo>/spikes/goblin3d/build_goblin.py", init_globals={"TASK": "frames"})

It works in a scene of its own, "Goblin", rebuilt from nothing on every run, so whatever else is open is left alone.
The model is one mesh with a part per bone (each cube follows one bone, no bending), facing -Y (glTF's +Z) with its
feet on the ground. Three clips, each an action on the rig at 24 fps: Idle and Walk loop, Attack plays once.

"frames" renders every clip from 8 directions into frames_raw/<clip>/<direction>/<frame>.png, small, unlit and
without smoothing: a stand-in for 3D Sprite Studio (which runs on Windows and Linux) so the terminal player has frames
to show. pixelate.py then shades and outlines them.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import bpy
from mathutils import Quaternion, Vector

HERE = Path(__file__).parent
S = 1 / 16  # one pixel's cube, in metres: the goblin stands about 1.25 m tall
FPS = 24
CENTRE, GROUND = 12, 23  # the sprite's middle (between columns 11 and 12) and the bottom of its feet, in pixels
TAG = "goblin3d"  # marks everything this script made, so a rebuild clears it out

# Where each bone points from its pivot (in sprite pixels): along the part, so Blender's bones look like the goblin.
TAILS = {
    "root": (12, 20), "torso": (12, 14), "head": (12, 3),
    "ear_l": (1.5, 5.5), "ear_r": (22.5, 5.5),
    "arm_l": (4.5, 19), "arm_r": (19.5, 19),
    "leg_l": (8, 23), "leg_r": (16, 23),
}


def world(px: float, py: float, depth: float = 0.0) -> Vector:
    """A point on the sprite (pixels from its top left; depth toward the viewer) in Blender's metres."""
    return Vector(((px - CENTRE) * S, -depth * S, (GROUND - py) * S))


def linear(hex_colour: str) -> tuple:
    """A sprite colour (sRGB) as the linear colour Blender's materials and glTF store."""
    def channel(c):
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return tuple(channel(int(hex_colour[i:i + 2], 16)) for i in (1, 3, 5))


# -- the model ----------------------------------------------------------------------------------------------------

# Each of a cube's faces: which way it points (x right, y down the sprite, z toward the viewer) and its corners.
FACES = {
    (-1, 0, 0): lambda x, y, z: [(x, y, z - .5), (x, y + 1, z - .5), (x, y + 1, z + .5), (x, y, z + .5)],
    (1, 0, 0):  lambda x, y, z: [(x + 1, y, z - .5), (x + 1, y + 1, z - .5), (x + 1, y + 1, z + .5), (x + 1, y, z + .5)],
    (0, -1, 0): lambda x, y, z: [(x, y, z - .5), (x + 1, y, z - .5), (x + 1, y, z + .5), (x, y, z + .5)],
    (0, 1, 0):  lambda x, y, z: [(x, y + 1, z - .5), (x + 1, y + 1, z - .5), (x + 1, y + 1, z + .5), (x, y + 1, z + .5)],
    (0, 0, -1): lambda x, y, z: [(x, y, z - .5), (x + 1, y, z - .5), (x + 1, y + 1, z - .5), (x, y + 1, z - .5)],
    (0, 0, 1):  lambda x, y, z: [(x, y, z + .5), (x + 1, y, z + .5), (x + 1, y + 1, z + .5), (x, y + 1, z + .5)],
}


def surface(parts: dict) -> tuple[list, list, list, dict]:
    """The outside of every part's cubes: vertices, faces (wound to face outward), each face's colour, and each
    part's vertex indices. Faces between two cubes of the same part are skipped; parts are each closed on their own,
    so a part that swings never opens a hole where it meets the next."""
    verts, faces, colours, groups = [], [], [], {}
    for part, spec in parts.items():
        cubes = {(x, y, z): colour for x, y, z, colour in spec["voxels"]}
        index = {}
        for (x, y, z), colour in cubes.items():
            for (dx, dy, dz), corners in FACES.items():
                if (x + dx, y + dy, z + dz) in cubes:
                    continue
                points = [world(*c) for c in corners(x, y, z)]
                outward = Vector((dx, -dz, -dy))
                if (points[1] - points[0]).cross(points[2] - points[1]).dot(outward) < 0:
                    points.reverse()
                face = []
                for p in points:
                    key = (part, round(p.x / S * 2), round(p.y / S * 2), round(p.z / S * 2))
                    if key not in index:
                        index[key] = len(verts)
                        verts.append(p)
                    face.append(index[key])
                faces.append(face)
                colours.append(colour)
        groups[part] = sorted(index.values())
    return verts, faces, colours, groups


def material(colour: str):
    mat = bpy.data.materials.new(f"goblin {colour}")
    mat[TAG] = True
    rgb = linear(colour)
    mat.diffuse_color = (*rgb, 1.0)  # what Blender's quick (Workbench) renders show
    nodes = mat.node_tree.nodes
    bsdf = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        bsdf = nodes.new("ShaderNodeBsdfPrincipled")
        out = next((n for n in nodes if n.type == "OUTPUT_MATERIAL"), None) or nodes.new("ShaderNodeOutputMaterial")
        mat.node_tree.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    bsdf.inputs["Base Color"].default_value = (*rgb, 1.0)
    bsdf.inputs["Roughness"].default_value = 1.0
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = 0.2
    return mat


def fresh_scene():
    """An empty "Goblin" scene, shown in Blender's window, with anything an earlier run made cleared away."""
    window = bpy.context.window_manager.windows[0]
    old = bpy.data.scenes.get("Goblin")
    if old:
        if window.scene == old:
            window.scene = next((s for s in bpy.data.scenes if s != old), None) or bpy.data.scenes.new("Scene")
        for obj in list(old.collection.all_objects):
            bpy.data.objects.remove(obj)
        bpy.data.scenes.remove(old)
    for store in (bpy.data.meshes, bpy.data.armatures, bpy.data.cameras, bpy.data.lights):
        for block in list(store):
            if block.name.startswith("goblin") and block.users == 0:
                store.remove(block)
    for store in (bpy.data.materials, bpy.data.actions):
        for block in list(store):
            if block.get(TAG):
                store.remove(block)
    scene = bpy.data.scenes.new("Goblin")
    window.scene = scene
    scene.render.fps = FPS
    scene.frame_start, scene.frame_end = 0, FPS
    return window, scene


def build_model(scene, data: dict):
    parts = {name: spec for name, spec in data["parts"].items() if spec["voxels"]}
    verts, faces, colours, groups = surface(parts)
    mesh = bpy.data.meshes.new("goblin")
    mesh.from_pydata([tuple(v) for v in verts], [], faces)
    palette = sorted(set(colours))
    for colour in palette:
        mesh.materials.append(material(colour))
    mesh.polygons.foreach_set("material_index", [palette.index(c) for c in colours])
    mesh.update()
    body = bpy.data.objects.new("goblin", mesh)
    scene.collection.objects.link(body)
    for part, indices in groups.items():
        body.vertex_groups.new(name=part).add(indices, 1.0, "REPLACE")
    return body, len(verts), len(faces), palette


def build_rig(window, scene, data: dict, body):
    rig = bpy.data.objects.new("goblin_rig", bpy.data.armatures.new("goblin_rig"))
    scene.collection.objects.link(rig)
    layer = scene.view_layers[0]
    with bpy.context.temp_override(window=window, scene=scene, view_layer=layer):
        layer.objects.active = rig
        rig.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
        for name, spec in data["parts"].items():  # parents come before their children in the JSON
            bone = rig.data.edit_bones.new(name)
            bone.head = world(*spec["pivot"])
            bone.tail = world(*TAILS[name])
            if spec["parent"]:
                bone.parent = rig.data.edit_bones[spec["parent"]]
        bpy.ops.object.mode_set(mode="OBJECT")
    body.parent = rig
    body.modifiers.new("Armature", "ARMATURE").object = rig
    for bone in rig.pose.bones:
        bone.rotation_mode = "QUATERNION"
    return rig


# -- the animation ------------------------------------------------------------------------------------------------
# A pose is, per bone, turns in degrees about Blender's own axes (x points right, y back, z up) and a nudge in pixels.
# Turning about x: a negative turn swings an arm or leg forward, a positive one tips the body or head forward.
# Ears turn about y to flap (left ear: positive is tip up; right ear: negative) and about z to lie back (left:
# negative; right: positive).


def P(rx=0.0, ry=0.0, rz=0.0, x=0.0, y=0.0, z=0.0):
    return (rx, ry, rz), (x, y, z)


def eased(t: float, keys: list) -> float:
    """A value that eases between (time, value) keys."""
    for (t0, v0), (t1, v1) in zip(keys, keys[1:]):
        if t <= t1:
            u = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
            return v0 + (v1 - v0) * u * u * (3 - 2 * u)
    return keys[-1][1]


def idle(t: float) -> dict:
    """Sinks a pixel and rises again, as the sprite's two frames do, breathing; the ears flap a beat behind."""
    w = 2 * math.pi * t
    sink = 0.5 - 0.5 * math.cos(w)
    flap = 10 * math.sin(w - 0.8)
    return {
        "torso": P(z=-sink),
        "head": P(rx=3 * math.sin(w)),
        "ear_l": P(ry=flap), "ear_r": P(ry=-flap),
        "arm_l": P(rx=-4 * math.sin(w), ry=5 * sink), "arm_r": P(rx=-4 * math.sin(w), ry=-5 * sink),
    }


def walk(t: float) -> dict:
    """Two steps on the spot: legs and arms swing opposite, the body dips as each foot lands and twists with the
    arms, the head keeps looking ahead, and the ears flap at every step."""
    w = 2 * math.pi * t
    s = math.sin(w)
    flap = 14 * math.sin(2 * w - 0.8)
    return {
        "torso": P(rx=6, rz=5 * s, z=-s * s),
        "head": P(rx=-4 + 2 * math.cos(2 * w), rz=-3 * s),
        "ear_l": P(ry=flap), "ear_r": P(ry=-flap),
        "arm_l": P(rx=30 * s), "arm_r": P(rx=-30 * s),
        "leg_l": P(rx=-28 * s), "leg_r": P(rx=28 * s),
    }


def attack(t: float) -> dict:
    """Rears back with both arms up and ears flat, then lunges forward and clubs down, and settles."""
    lean = eased(t, [(0, 0), (.38, -14), (.5, 14), (.62, 14), (1, 0)])
    arms = eased(t, [(0, 0), (.38, 150), (.5, -60), (.62, -60), (1, 0)])
    spread = eased(t, [(0, 0), (.38, 35), (.5, 10), (.62, 10), (1, 0)])
    head = eased(t, [(0, 0), (.38, -8), (.5, 10), (.62, 10), (1, 0)])
    ears = eased(t, [(0, 0), (.38, -25), (.5, 15), (.7, 0), (1, 0)])
    brace = eased(t, [(0, 0), (.38, 8), (.5, -20), (.7, -20), (1, 0)])
    return {
        "root": P(y=eased(t, [(0, 0), (.38, 1), (.5, -2), (.7, -2), (1, 0)]),
                  z=eased(t, [(0, 0), (.38, 0), (.44, 1.5), (.5, 0), (1, 0)])),
        "torso": P(rx=lean),
        "head": P(rx=head),
        "ear_l": P(rz=ears), "ear_r": P(rz=-ears),
        "arm_l": P(rx=arms, ry=spread), "arm_r": P(rx=arms, ry=-spread),
        "leg_l": P(rx=brace), "leg_r": P(rx=-0.7 * brace),
    }


CLIPS = {"Idle": (idle, 24, True), "Walk": (walk, 24, True), "Attack": (attack, 24, False)}


def animate(rig, name: str, pose, frames: int, loop: bool):
    action = bpy.data.actions.new(name)
    action[TAG] = True
    action.use_fake_user = True
    rig.animation_data_create()
    rig.animation_data.action = action
    for f in range(frames + 1):
        posed = pose(f / frames)
        for bone in rig.pose.bones:
            (rx, ry, rz), nudge = posed.get(bone.name, P())
            turn = (Quaternion((0, 0, 1), math.radians(rz)) @ Quaternion((1, 0, 0), math.radians(rx))
                    @ Quaternion((0, 1, 0), math.radians(ry)))
            rest = bone.bone.matrix_local.to_quaternion()  # turns and nudges are given in the rig's axes
            bone.rotation_quaternion = rest.inverted() @ turn @ rest
            bone.location = rest.inverted() @ (Vector(nudge) * S)
            bone.keyframe_insert("rotation_quaternion", frame=f, group=bone.name)
            bone.keyframe_insert("location", frame=f, group=bone.name)
    action.use_frame_range = True
    action.frame_start, action.frame_end = 0, frames
    action.use_cyclic = loop
    return action


def stage(scene):
    """A camera and a sun so the scene shows something in Blender (neither goes into the .glb)."""
    cam = bpy.data.objects.new("goblin_camera", bpy.data.cameras.new("goblin_camera"))
    cam.data.type = "ORTHO"
    scene.collection.objects.link(cam)
    scene.camera = cam
    aim(cam, yaw=30, elevation=20, scale=32)
    sun = bpy.data.objects.new("goblin_sun", bpy.data.lights.new("goblin_sun", "SUN"))
    sun.data.energy = 3.0
    sun.rotation_euler = (math.radians(50), 0, math.radians(-30))
    scene.collection.objects.link(sun)


def aim(cam, yaw: float, elevation: float, scale: int):
    """Points the camera at the goblin from `yaw` degrees round (0 is straight in front, turning to its left),
    looking down by `elevation`, framing `scale` pixels across."""
    a, e = math.radians(yaw), math.radians(elevation)
    centre = world(CENTRE, GROUND - 11)
    cam.location = centre + Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e))) * 10
    cam.rotation_euler = (math.pi / 2 - e, 0, a)
    cam.data.ortho_scale = scale * S


def build() -> dict:
    data = json.loads((HERE / "goblin_voxels.json").read_text())
    window, scene = fresh_scene()
    body, n_verts, n_faces, palette = build_model(scene, data)
    rig = build_rig(window, scene, data, body)
    stage(scene)
    actions = [animate(rig, name, pose, frames, loop) for name, (pose, frames, loop) in CLIPS.items()]
    rig.animation_data.action = actions[0]
    scene.frame_set(0)
    glb = HERE / "goblin.glb"
    with bpy.context.temp_override(window=window, scene=scene, view_layer=scene.view_layers[0]):
        bpy.ops.export_scene.gltf(
            filepath=str(glb), export_format="GLB", use_active_scene=True,
            export_animations=True, export_animation_mode="ACTIONS", export_force_sampling=True,
            export_frame_range=False, export_anim_slide_to_zero=False, export_reset_pose_bones=True,
            export_skins=True, export_def_bones=False, export_yup=True, export_apply=False,
        )
    blend = HERE / "goblin.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend), copy=True)
    return {"verts": n_verts, "faces": n_faces, "colours": palette, "bones": [b.name for b in rig.data.bones],
            "clips": [a.name for a in actions], "glb": str(glb), "glb_bytes": glb.stat().st_size, "blend": str(blend)}


# -- stand-in sprite frames ---------------------------------------------------------------------------------------

FRAMES = {"Idle": 4, "Walk": 8, "Attack": 8}  # how many frames each clip is cut into


def render_frames(size: int = 32, directions: int = 8, elevation: float = 20) -> dict:
    scene = bpy.data.scenes["Goblin"]
    rig, cam = scene.objects["goblin_rig"], scene.camera
    render = scene.render
    render.engine = "BLENDER_WORKBENCH"
    render.resolution_x = render.resolution_y = size
    render.resolution_percentage = 100
    render.film_transparent = True
    render.image_settings.file_format = "PNG"
    render.image_settings.color_mode = "RGBA"
    scene.display.render_aa = "OFF"
    scene.display.shading.light = "FLAT"  # the sprite's exact colours: pixelate.py shades them the artist's way
    scene.display.shading.color_type = "MATERIAL"
    scene.view_settings.view_transform = "Standard"
    out = HERE / "frames_raw"
    count = 0
    for clip, n in FRAMES.items():
        action = bpy.data.actions[clip]
        rig.animation_data.action = action
        length = int(action.frame_end - action.frame_start)
        for d in range(directions):
            aim(cam, yaw=360 * d / directions, elevation=elevation, scale=size)
            for i in range(n):
                scene.frame_set(round(i * length / n))
                render.filepath = str(out / clip / str(d) / f"{i:02d}.png")
                bpy.ops.render.render(write_still=True, scene=scene.name)
                count += 1
    rig.animation_data.action = bpy.data.actions["Idle"]
    aim(cam, yaw=30, elevation=20, scale=32)
    return {"frames": count, "folder": str(out)}


RESULT = {"build": build, "frames": render_frames}[globals().get("TASK", "build")]()
