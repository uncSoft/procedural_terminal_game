"""Spike: the Goblin King rigged and animated in Blender, exported as goblin_king.glb, and rendered to big frames.

Reads the smooth model inflate_king.py wrote (king/king_mesh.json). Runs headless, so the Blender you have open is
left alone:

    B=/Applications/Blender.app/Contents/MacOS/Blender
    $B -b --factory-startup --python spikes/goblin3d/build_king.py -- build          # king/goblin_king.glb + .blend
    $B -b spikes/goblin3d/king/goblin_king.blend --python spikes/goblin3d/build_king.py -- frames

or from the Blender MCP: runpy.run_path(path, init_globals={"TASK": "build"}).

The model is one mesh, every part following one bone, facing -Y (glTF's +Z) with its feet on the ground. Two clips at
24 fps: Entrance (once: he drops in, slips, recovers, raises his pan and slams it down) ends on Idle's first pose, and
Idle loops.

"frames" renders every clip from 8 directions into king/frames_hd/<clip>/<direction>/<frame>.png, 256 pixels a side,
toon-shaded in the sprite's own colours: lit or shadowed, no blending, so reduce.py can shrink them to any size. The
light comes from the viewer's upper left whichever way he's turned, as it does in drawn sprites.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Quaternion, Vector

HERE = Path(__file__).parent
OUT = HERE / "king"
S = 1 / 16  # a sprite pixel, in metres: he stands about 1.4 m tall
FPS = 24
CENTRE, GROUND = 12, 22  # the sprite's middle and the bottom of his boots, in pixels
TAG = "goblin_king"
LIGHT = Vector((-0.6, 0.5, -0.62)).normalized()  # toward the light, in camera space (x right, y up, z ahead)
LIT_FROM = 0.25  # how square-on the light has to be to light a surface
SPAN = 48  # how many sprite pixels the frames show across: room for him to drop in and swing his pan


def world(px: float, py: float, depth: float = 0.0) -> Vector:
    """A point on the sprite (pixels from its top left; depth toward the viewer) in Blender's metres."""
    return Vector(((px - CENTRE) * S, -depth * S, (GROUND - py) * S))


def linear(hex_colour: str) -> tuple:
    def channel(c):
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return tuple(channel(int(hex_colour[i:i + 2], 16)) for i in (1, 3, 5))


# -- the model ----------------------------------------------------------------------------------------------------

def material(lit: str, shade: str):
    """A colour as two ways of drawing it: a plain Principled BSDF for the .glb (3D Sprite Studio lights it itself),
    and a toon shader for our frames, which picks the lit or the shadow colour by which way the surface faces the
    camera. toon() switches between them."""
    mat = bpy.data.materials.new(f"{TAG} {lit}")
    mat[TAG] = True
    mat.diffuse_color = (*linear(lit), 1.0)
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = (*linear(lit), 1.0)
    bsdf.inputs["Roughness"].default_value = 1.0
    bsdf.inputs["Specular IOR Level"].default_value = 0.2
    normal = nodes.new("ShaderNodeNewGeometry")
    to_camera = nodes.new("ShaderNodeVectorTransform")
    to_camera.vector_type, to_camera.convert_from, to_camera.convert_to = "NORMAL", "WORLD", "CAMERA"
    facing = nodes.new("ShaderNodeVectorMath")
    facing.operation = "DOT_PRODUCT"
    facing.inputs[1].default_value = LIGHT
    lit_up = nodes.new("ShaderNodeMath")
    lit_up.operation = "GREATER_THAN"
    lit_up.inputs[1].default_value = LIT_FROM
    shadow, light = nodes.new("ShaderNodeEmission"), nodes.new("ShaderNodeEmission")
    shadow.inputs["Color"].default_value = (*linear(shade), 1.0)
    light.inputs["Color"].default_value = (*linear(lit), 1.0)
    pick = nodes.new("ShaderNodeMixShader")
    pick.name = "toon"
    links.new(normal.outputs["Normal"], to_camera.inputs["Vector"])
    links.new(to_camera.outputs["Vector"], facing.inputs[0])
    links.new(facing.outputs["Value"], lit_up.inputs[0])
    links.new(lit_up.outputs[0], pick.inputs[0])
    links.new(shadow.outputs[0], pick.inputs[1])
    links.new(light.outputs[0], pick.inputs[2])
    links.new(bsdf.outputs[0], out.inputs["Surface"])
    return mat


def toon(on: bool) -> None:
    for mat in bpy.data.materials:
        if mat.get(TAG):
            nodes = mat.node_tree.nodes
            source = nodes["toon"] if on else next(n for n in nodes if n.type == "BSDF_PRINCIPLED")
            out = next(n for n in nodes if n.type == "OUTPUT_MATERIAL")
            mat.node_tree.links.new(source.outputs[0], out.inputs["Surface"])


def build_model(scene, data: dict):
    verts, faces, colours, owner = [], [], [], []
    for name, part in data["parts"].items():
        base = len(verts)
        verts += [world(*v) for v in part["verts"]]
        faces += [[base + i for i in face] for face in part["faces"]]
        colours += part["colours"]
        owner += [name] * len(part["verts"])
    mesh = bpy.data.meshes.new(TAG)
    mesh.from_pydata([tuple(v) for v in verts], [], faces)
    palette = sorted(set(colours))
    for colour in palette:
        mesh.materials.append(material(colour, data["shades"][colour]))
    mesh.polygons.foreach_set("material_index", [palette.index(c) for c in colours])
    # Round off the pixel steps along each smooth part's edge (sideways only, so the swelling keeps its depth), and
    # turn the crown's and the pan's faces outward.
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.verts.ensure_lookup_table()
    for name, part in data["parts"].items():
        mine = [v for v in bm.verts if owner[v.index] == name]
        if part.get("smooth"):
            for _ in range(2):
                bmesh.ops.smooth_vert(bm, verts=mine, factor=0.5, use_axis_x=True, use_axis_y=False, use_axis_z=True)
        if part.get("recalc"):
            mine = set(mine)
            bmesh.ops.recalc_face_normals(bm, faces=[f for f in bm.faces if f.verts[0] in mine])
    bm.to_mesh(mesh)
    bm.free()
    mesh.shade_smooth()
    mesh.set_sharp_from_angle(angle=math.radians(50))
    body = bpy.data.objects.new(TAG, mesh)
    scene.collection.objects.link(body)
    groups = {bone: body.vertex_groups.new(name=bone) for bone in data["bones"]}
    base = 0
    for part in data["parts"].values():
        if "weights" in part:  # a part that bends (a tail): each vertex shared by the bones either side of it
            for i, weights in enumerate(part["weights"]):
                for bone, weight in weights.items():
                    groups[bone].add([base + i], weight, "REPLACE")
        else:
            groups[part["bone"]].add(list(range(base, base + len(part["verts"]))), 1.0, "REPLACE")
        base += len(part["verts"])
    return body, len(verts), len(faces), palette


def build_rig(scene, data: dict, body):
    rig = bpy.data.objects.new(f"{TAG}_rig", bpy.data.armatures.new(f"{TAG}_rig"))
    scene.collection.objects.link(rig)
    layer = bpy.context.view_layer
    layer.objects.active = rig
    rig.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    for name, bone in data["bones"].items():  # parents come before their children
        edit = rig.data.edit_bones.new(name)
        edit.head, edit.tail = world(*bone["head"]), world(*bone["tail"])
        if bone["parent"]:
            edit.parent = rig.data.edit_bones[bone["parent"]]
    bpy.ops.object.mode_set(mode="OBJECT")
    body.parent = rig
    body.modifiers.new("Armature", "ARMATURE").object = rig
    for bone in rig.pose.bones:
        bone.rotation_mode = "QUATERNION"
    return rig


# -- the animation ------------------------------------------------------------------------------------------------
# A pose is, per bone, turns in degrees about the rig's own axes (x points to the viewer's right, y away from the
# viewer, z up), a nudge in pixels, and a squash (sq: below 1 squat and wide, above 1 tall and thin).
# A negative turn about x swings a hanging arm or leg forward; a positive one tips the body or head forward.
# A positive turn about y tips the top of a part toward the viewer's right. Ears turn about y to flap (left ear:
# positive is tip up; right ear: negative) and about z to lie back (left: negative; right: positive).
# The pan hangs on from his hand down the line of his arm: 0 holds it out like a club, -120 stands it up.


def P(rx=0.0, ry=0.0, rz=0.0, x=0.0, y=0.0, z=0.0, sq=1.0, size=1.0, wide=None):
    """size scales the bone and everything on it; wide, when given, sets its width apart from the squash."""
    wide = 1 / math.sqrt(sq) if wide is None else wide
    return (rx, ry, rz), (x, y, z), (wide * size, sq * size, wide * size)  # a bone's own y runs along it


def eased(t: float, keys: list) -> float:
    """A value that eases between (time, value) keys."""
    if t <= keys[0][0]:
        return keys[0][1]
    for (t0, v0), (t1, v1) in zip(keys, keys[1:]):
        if t <= t1:
            u = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
            return v0 + (v1 - v0) * u * u * (3 - 2 * u)
    return keys[-1][1]


ENTRANCE = 72  # frames: three seconds


def entrance(t: float) -> dict:
    """The King arrives. 0-8: he drops in from above, stretched thin, pan held high, cape streaming and crown
    floating off his head. 8-15: lands in a squat; the crown comes down after him and bonks on crooked. 15-34: the
    floor is greasy (it always is): one foot shoots out sideways into the splits, he teeters and windmills. 34-40: stamps it down, shakes his
    head. 40-55: rises on his toes and lifts the pan high, cape billowing: behold. 55-64: hops and slams it down,
    BONG. 64-72: settles, the pan stood up like a sceptre, ready to fight (Idle's first pose)."""
    f = t * ENTRANCE

    def k(*keys):
        return eased(f, list(keys))

    fall = 44 * (1 - (f / 8) ** 2) if f < 8 else 0.0  # faster and faster, like a dropped thing
    slipping = k((15, 0), (18, 1), (30, 1), (33, 0)) if 15 <= f <= 33 else 0.0
    flail = math.sin(2 * math.pi * (f - 15) / 9) * slipping  # arms round in circles: forward and back...
    swirl = math.cos(2 * math.pi * (f - 15) / 9) * slipping  # ...and out and in
    flap = math.sin(2 * math.pi * (f - 15) / 5) * k((15, 0), (17, 1), (31, 1), (34, 0)) if 15 <= f <= 34 else 0.0
    tremble = math.sin(f * 2.4) * k((46, 0), (48, 1), (54, 1), (55, 0))
    ears = k((0, 30), (8, 30), (10, -30), (14, 10), (17, 0), (44, 0), (48, 18), (55, 18), (57, 20), (59, -25),
             (62, 10), (66, 0)) + 25 * flap
    ears_back = k((0, -30), (8, -30), (12, 0))
    return {
        "root": P(rx=k((15, 0), (19, -8), (23, -4), (27, -8), (31, -3), (34, 4), (37, -1), (40, 0), (48, -6),
                       (55, -6), (58, 5), (61, 4), (66, 0)),
                  ry=k((15, 0), (19, -14), (23, -6), (27, -13), (31, -5), (34, 4), (37, -1), (40, 0), (55, 0),
                       (59, -8), (64, 0)),
                  z=fall + k((15, 0), (19, -1.5), (31, -1.5), (34, 0), (44, 0), (48, 0.8), (55, 0.8), (57, 1.8),
                             (59, 0)),
                  sq=k((0, 1.12), (7.9, 1.12), (9.5, 0.74), (11, 0.8), (13, 1.08), (15, 0.97), (17, 1.0), (33, 1.0),
                       (34.5, 0.9), (36, 1.0), (44, 1.0), (48, 1.05), (55, 1.05), (57, 1.1), (59, 0.85), (61, 0.9),
                       (64, 1.03), (68, 1.0))),
        "torso": P(rx=k((8, 0), (10, 6), (14, 0)), rz=k((55, 0), (59, -12), (64, 0))),
        "head": P(rx=k((0, -10), (8, -10), (10, 5), (14, -2), (17, 0), (40, 0), (48, -12), (55, -12), (58, 3),
                       (62, 2), (68, 0)),
                  rz=k((15, 0), (20, 15), (25, -15), (30, 10), (34, 0), (35.5, 12), (37, -12), (38.5, 8), (40, 0))),
        "crown": P(ry=k((0, -8), (8, 6), (11, 0), (12.5, -14), (14, -18), (33, -18), (35, 6), (37, -10), (39, -4),
                        (40, -6), (59, -6), (60.5, 6), (62.5, -9), (66, -6)),
                   rz=k((0, 25), (11, 0)),
                   z=k((0, 4), (8, 3.5), (11, 0), (12.5, 0.8), (14, 0), (59, 0), (60, 1.0), (61.5, 0))),
        "ear_l": P(ry=ears, rz=ears_back), "ear_r": P(ry=-ears, rz=-ears_back),
        "arm_l": P(rx=k((0, -165), (8, -165), (11, -55), (14, -45), (40, -40), (47, -178), (55, -172), (57, -188),
                        (59.5, -45), (62, -50), (70, -50)) + 60 * flail + 3 * tremble,
                   ry=k((0, 20), (8, 20), (11, 28), (14, 20), (17, 22), (31, 22), (34, 20), (40, 15), (47, 12),
                        (55, 12), (59.5, 28), (62, 25), (70, 18)) + 18 * swirl),
        "pan": P(rx=k((8, 0), (11, -60), (14, -90), (31, -90), (36, -40), (40, 0), (62, 0), (70, -120)) + 15 * flap),
        "arm_r": P(rx=k((0, -140), (8, -140), (11, -10), (14, -15), (40, -15), (47, -25), (55, -25), (59.5, -25),
                        (62, -15), (70, -8)) - 70 * flail,
                   ry=k((0, -40), (8, -40), (11, -30), (14, -15), (17, -35), (31, -35), (34, -12), (40, -12),
                        (47, -80), (55, -78), (59.5, -35), (62, -20), (70, -10)) - 30 * swirl),
        "leg_l": P(rx=k((0, -25), (8, -25), (10, 0), (57, 0), (59, -12), (64, 0)),
                   ry=k((15, 0), (18, 8), (33, 8), (35, 0))),
        "leg_r": P(rx=k((0, -10), (8, -10), (10, 0), (15, 0), (18, -25), (33, -25), (34.5, 5), (36, 0), (57, 0),
                        (59, 10), (64, 0)),
                   ry=k((15, 0), (18, -50), (30, -42), (33, -50), (34.5, 0))),
        "cape": P(rx=k((0, 110), (8, 110), (10, -15), (13, 10), (16, 0), (40, 0), (48, 25), (55, 20), (57, 30),
                       (60, -10), (64, 5), (68, 0)) + 10 * flail),
    }


def idle(t: float) -> dict:
    """Ready to fight: breathing, the pan bobbing in his fist a beat ahead of its wobble, ears twitching, the crown
    still a little crooked."""
    w = 2 * math.pi * t
    sink = 0.5 - 0.5 * math.cos(w)
    return {
        "root": P(sq=1 - 0.035 * sink),
        "torso": P(z=-0.4 * sink),
        "head": P(rx=3 * math.sin(w - 0.4)),
        "crown": P(ry=-6 + 2 * math.sin(w - 1.0)),
        "ear_l": P(ry=8 * math.sin(w - 0.8)), "ear_r": P(ry=-8 * math.sin(w - 0.8)),
        "arm_l": P(rx=-50 + 6 * math.sin(w), ry=18),
        "pan": P(rx=-120 + 8 * math.sin(w - 0.6)),
        "arm_r": P(rx=-8 - 4 * math.sin(w), ry=-10),
        "cape": P(rx=4 * math.sin(w - 1.2)),
    }


CLIPS = {"Entrance": (entrance, ENTRANCE, False), "Idle": (idle, 24, True)}


def animate(rig, name: str, pose, frames: int, loop: bool):
    action = bpy.data.actions.new(name)
    action[TAG] = True
    action.use_fake_user = True
    rig.animation_data_create()
    rig.animation_data.action = action
    for f in range(frames + 1):
        posed = pose(f / frames)
        for bone in rig.pose.bones:
            (rx, ry, rz), nudge, scale = posed.get(bone.name, P())
            turn = (Quaternion((0, 0, 1), math.radians(rz)) @ Quaternion((1, 0, 0), math.radians(rx))
                    @ Quaternion((0, 1, 0), math.radians(ry)))
            rest = bone.bone.matrix_local.to_quaternion()  # turns and nudges are given in the rig's axes
            bone.rotation_quaternion = rest.inverted() @ turn @ rest
            bone.location = rest.inverted() @ (Vector(nudge) * S)
            bone.scale = scale
            for path in ("rotation_quaternion", "location", "scale"):
                bone.keyframe_insert(path, frame=f, group=bone.name)
    action.use_frame_range = True
    action.frame_start, action.frame_end = 0, frames
    action.use_cyclic = loop
    return action


def aim(cam, yaw: float, elevation: float, span: float):
    """Points the camera at the King from `yaw` degrees round (0 is straight in front, turning to his left), looking
    down by `elevation`, framing `span` pixels across, from just below his feet to well above his crown."""
    a, e = math.radians(yaw), math.radians(elevation)
    centre = world(CENTRE, GROUND - 0.38 * span)
    cam.location = centre + Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e))) * 10
    cam.rotation_euler = (math.pi / 2 - e, 0, a)
    cam.data.ortho_scale = span * S


def build() -> dict:
    data = json.loads((OUT / "king_mesh.json").read_text())
    scene = bpy.context.scene
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
    scene.name = "GoblinKing"
    scene.render.fps = FPS
    scene.frame_start, scene.frame_end = 0, ENTRANCE
    body, n_verts, n_faces, palette = build_model(scene, data)
    rig = build_rig(scene, data, body)
    cam = bpy.data.objects.new(f"{TAG}_camera", bpy.data.cameras.new(f"{TAG}_camera"))
    cam.data.type = "ORTHO"
    scene.collection.objects.link(cam)
    scene.camera = cam
    aim(cam, yaw=30, elevation=12, span=SPAN)
    sun = bpy.data.objects.new(f"{TAG}_sun", bpy.data.lights.new(f"{TAG}_sun", "SUN"))
    sun.data.energy = 3.0
    sun.rotation_euler = (math.radians(50), 0, math.radians(-30))
    scene.collection.objects.link(sun)
    actions = [animate(rig, name, pose, frames, loop) for name, (pose, frames, loop) in CLIPS.items()]
    rig.animation_data.action = actions[0]
    scene.frame_set(0)
    toon(False)
    glb = OUT / "goblin_king.glb"
    bpy.ops.export_scene.gltf(
        filepath=str(glb), export_format="GLB", use_active_scene=True,
        export_animations=True, export_animation_mode="ACTIONS", export_force_sampling=True,
        export_frame_range=False, export_anim_slide_to_zero=False, export_reset_pose_bones=True,
        export_skins=True, export_def_bones=False, export_yup=True, export_apply=False,
    )
    blend = OUT / "goblin_king.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    return {"verts": n_verts, "faces": n_faces, "colours": palette, "bones": [b.name for b in rig.data.bones],
            "clips": [a.name for a in actions], "glb": str(glb), "glb_bytes": glb.stat().st_size, "blend": str(blend)}


# -- big frames ---------------------------------------------------------------------------------------------------

def render_frames(size: int = 256, directions: int = 8, elevation: float = 12, span: float = SPAN,
                  clips: tuple = tuple(CLIPS)) -> dict:
    scene = bpy.data.scenes["GoblinKing"]
    rig, cam = scene.objects[f"{TAG}_rig"], scene.camera
    toon(True)
    render = scene.render
    render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = 1  # one sample: no blending, every pixel a palette colour
    render.filter_size = 0.0
    render.resolution_x = render.resolution_y = size
    render.resolution_percentage = 100
    render.film_transparent = True
    render.image_settings.file_format = "PNG"
    render.image_settings.color_mode = "RGBA"
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    out = OUT / "frames_hd"
    count = 0
    for clip in clips:
        _, frames, loop = CLIPS[clip]
        rig.animation_data.action = bpy.data.actions[clip]
        scene.frame_start, scene.frame_end = 0, frames - 1 if loop else frames
        for d in range(directions):
            aim(cam, yaw=360 * d / directions, elevation=elevation, span=span)
            render.filepath = str(out / clip / str(d)) + "/"
            bpy.ops.render.render(animation=True, scene=scene.name)
            count += scene.frame_end + 1
    toon(False)
    return {"frames": count, "folder": str(out)}


def test_frame(frame: int = 64, yaw: float = 0) -> dict:
    """One frame, to check the light and the framing."""
    scene = bpy.data.scenes["GoblinKing"]
    toon(True)
    scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = 1
    scene.render.resolution_x = scene.render.resolution_y = 256
    scene.render.film_transparent = True
    scene.view_settings.view_transform = "Standard"
    scene.objects[f"{TAG}_rig"].animation_data.action = bpy.data.actions["Entrance"]
    aim(scene.camera, yaw=yaw, elevation=12, span=SPAN)
    scene.frame_set(int(frame))
    scene.render.filepath = str(OUT / f"test_{int(frame)}_{int(yaw)}.png")
    bpy.ops.render.render(write_still=True, scene=scene.name)
    return {"test": scene.render.filepath}


def main(task: str, *args) -> dict:
    if task == "build":
        return build()
    if task == "frames":
        return render_frames(clips=tuple(args) or tuple(CLIPS))
    if task == "test":
        return test_frame(*(float(a) for a in args))
    raise SystemExit(f"unknown task {task!r}: build, frames or test")


if "TASK" in globals():
    RESULT = main(globals()["TASK"])
elif __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else ["build"]
    print("RESULT", json.dumps(main(*argv)))
