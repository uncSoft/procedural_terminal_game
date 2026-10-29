"""Spike: an item as a model that turns, for a preview in the game: the Jar o' Light (drawn by BelleDaBest).

Her sprite: a glass jar with a wooden lid, drawn as just its outline (pale down its lit side, slate elsewhere), full of
glowing cave bugs in four colours (each a round body and two wings) and sparks of white light. The model is built round
from that outline and finer than the bosses: a turned glass jar and lid, eight bugs flying round inside it with their
wings buzzing, and sparks twinkling. Unlike the bosses, it's meant to be seen from every side.

Runs headless:

    B=/Applications/Blender.app/Contents/MacOS/Blender
    $B -b --factory-startup --python spikes/goblin3d/build_jar.py -- build     # jar_o_light/jar_o_light.glb + .blend
    $B -b spikes/goblin3d/jar_o_light/jar_o_light.blend --python spikes/goblin3d/build_jar.py -- frames
    $B -b spikes/goblin3d/jar_o_light/jar_o_light.blend --python spikes/goblin3d/build_jar.py -- test 0 8 16

"frames" renders one looping clip, Idle (48 frames at 24 fps), from DIRECTIONS turns round the jar into
jar_o_light/frames_hd/Idle/<turn>/<frame>.png, 256 pixels a side, with the glass left out (it's see-through), and the
glass on its own once into jar_o_light/glass.png. reduce_jar.py shrinks them and draws the glass's outline from it.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import build_king as kit  # noqa: E402
from build_king import S, material, toon, world  # noqa: E402

TAG = kit.TAG = "jar_o_light"  # the King's helpers name and find what they make by it
kit.GROUND = 23  # the bottom of the jar
OUT = HERE / "jar_o_light"
SCENE = "JarOLight"
SPAN, ELEVATION = 32, 8  # pixels across the frame; looking down a little, to see round the lid and the jar's foot
MIDDLE = 11.5  # the frames are centred on the jar, not stood on the floor as the bosses are
DIRECTIONS, FRAMES = 32, 48

TAN, BROWN = "#c28569", "#b86f50"
SLATE, PALE, WHITE = "#5a6988", "#c0cbdc", "#ffffff"
YELLOW, GREEN, PLUM, ORANGE, BLUE, CYAN, RED = ("#fee761", "#63c74d", "#68386c", "#ff441a", "#124e89", "#2ce8f5",
                                                "#ff5257")
# Its lid shades from tan to the brown of its rim, as drawn. The bugs and sparks glow: they keep their colour all round.
SHADES = {TAN: BROWN, BROWN: BROWN, WHITE: WHITE, YELLOW: YELLOW, GREEN: GREEN, PLUM: PLUM, ORANGE: ORANGE,
          BLUE: BLUE, CYAN: CYAN, RED: RED, SLATE: SLATE, PALE: PALE}
# What reduce_jar.py counts heavier when it shrinks it, so the small bright things survive.
HEAVIER = {WHITE: 2.5, YELLOW: 1.6, GREEN: 1.6, PLUM: 1.6, ORANGE: 1.6, BLUE: 1.6, CYAN: 1.6, RED: 1.6}


# -- the jar -------------------------------------------------------------------------------------------------------

# The glass's half-width down from under the lid to the bottom, inside the outline the sprite drew round it: a neck, a
# round shoulder, a straight body and a foot a little narrower. (Sprite pixels, the jar's middle at x 12.)
GLASS = [(3.6, 6.0), (5.0, 6.1), (6.0, 6.8), (7.0, 7.6), (8.0, 8.0), (9.5, 8.4), (10.5, 8.9), (11.5, 9.0), (17.0, 9.0),
         (18.0, 8.7), (19.0, 8.2), (21.4, 8.0), (21.85, 7.7), (22.0, 7.2), (22.0, 0.0)]
# The lid: a wooden disc with a fat rim round it, sitting down in the neck.
LID = [(0.8, 0.0), (0.8, 7.4), (0.95, 7.85), (1.4, 8.1), (2.0, 8.85), (2.7, 8.95), (3.2, 8.6), (3.5, 7.9), (3.9, 7.6),
       (4.2, 6.2), (4.2, 0.0)]


def inner(y: float) -> float:
    """How far from the middle the glass is at height y."""
    for (y0, r0), (y1, r1) in zip(GLASS, GLASS[1:]):
        if y0 <= y <= y1 and y1 > y0:
            return r0 + (r1 - r0) * (y - y0) / (y1 - y0)
    return GLASS[0][1] if y < GLASS[0][0] else GLASS[-2][1]


def facing(name: str, lit: str, shade: str, square: float):
    """A colour lit where the surface faces you (more square-on than `square`) or faces up, and in shade where it
    turns away: the way the sprite shades its lid, darker at the ends of its rim, whichever way the jar is turned.
    Built like build_king.material, so toon() switches it the same way."""
    mat = material(lit, shade)
    mat.name = f"{TAG} {name}"
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    pick = nodes["toon"]
    geometry = nodes.new("ShaderNodeNewGeometry")
    towards = nodes.new("ShaderNodeVectorMath")
    towards.operation = "DOT_PRODUCT"
    links.new(geometry.outputs["Normal"], towards.inputs[0])
    links.new(geometry.outputs["Incoming"], towards.inputs[1])
    square_on = nodes.new("ShaderNodeMath")
    square_on.operation, square_on.inputs[1].default_value = "GREATER_THAN", square
    links.new(towards.outputs["Value"], square_on.inputs[0])
    up = nodes.new("ShaderNodeSeparateXYZ")
    links.new(geometry.outputs["Normal"], up.inputs[0])
    on_top = nodes.new("ShaderNodeMath")
    on_top.operation, on_top.inputs[1].default_value = "GREATER_THAN", 0.6
    links.new(up.outputs["Z"], on_top.inputs[0])
    either = nodes.new("ShaderNodeMath")
    either.operation = "MAXIMUM"
    links.new(square_on.outputs[0], either.inputs[0])
    links.new(on_top.outputs[0], either.inputs[1])
    links.new(either.outputs[0], pick.inputs[0])
    return mat


# The lid is painted by name, not colour: tan, browning toward its ends, its fat rim lit only in its middle.
LID_PAINT = {"lid": (TAN, BROWN, 0.3), "lid rim": (TAN, BROWN, 0.88)}


def materials_for(mesh, colours: list) -> list:
    palette = sorted(set(colours))
    for colour in palette:
        name = f"{TAG} {colour}"
        if colour in LID_PAINT:
            mesh.materials.append(bpy.data.materials.get(name) or facing(colour, *LID_PAINT[colour]))
        else:
            mesh.materials.append(bpy.data.materials.get(name) or material(colour, SHADES[colour]))
    return palette


def make(name: str, verts: list, faces: list, colours: list, at: Vector | None = None, parent=None):
    """An object from vertices (in metres, about its own middle), faces and a colour per face, its faces turned out."""
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([tuple(v) for v in verts], [], faces)
    palette = materials_for(mesh, colours)
    mesh.polygons.foreach_set("material_index", [palette.index(c) for c in colours])
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(mesh)
    bm.free()
    mesh.shade_smooth()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    if at is not None:
        obj.location = at
    if parent:
        obj.parent = parent
    return obj


def lathe(name: str, profile: list, paint, sides: int = 128):
    """A round thing turned about the jar's middle: (height, radius) from its top down; paint(height) colours it."""
    verts, faces, colours = [], [], []
    for y, r in profile:
        for k in range(sides):
            a = 2 * math.pi * k / sides
            verts.append(world(12 + r * math.sin(a), y, r * math.cos(a)))
    for n in range(1, len(profile)):
        r0, r1 = (n - 1) * sides, n * sides
        for k in range(sides):
            faces.append([r0 + k, r1 + k, r1 + (k + 1) % sides, r0 + (k + 1) % sides])
            colours.append(paint((profile[n - 1][0] + profile[n][0]) / 2))
    return make(name, verts, faces, colours)


def sphere(radius: tuple, segments: int = 16, rings: int = 10) -> tuple[list, list]:
    """A ball, squashed to the radii (across, deep, up), in metres about its middle."""
    verts, faces = [], []
    for j in range(rings + 1):
        v = math.pi * j / rings
        for k in range(segments):
            u = 2 * math.pi * k / segments
            verts.append(Vector((radius[0] * math.sin(v) * math.cos(u), radius[1] * math.sin(v) * math.sin(u),
                                 radius[2] * math.cos(v))) * S)
    for j in range(rings):
        for k in range(segments):
            a, b = j * segments + k, j * segments + (k + 1) % segments
            faces.append([a, b, b + segments, a + segments])
    return verts, faces


# -- the bugs and the sparks ---------------------------------------------------------------------------------------

# Two of each kind, as drawn: (wings, body), and where each flies. At the loop's start, seen from the front, each is
# where the sprite put it: r pixels from the jar's middle at angle a (0 toward the viewer), at height y. Each goes round
# `turns` times a loop (negative: the other way), bobbing `bob` pixels up and down `bobs` times.
BUGS = [
    ((YELLOW, GREEN), dict(r=4.5, a=-63, y=8.5, turns=1, bob=1.5, bobs=1, phase=0.0)),
    ((YELLOW, GREEN), dict(r=3.0, a=180, y=12.5, turns=-1, bob=2.0, bobs=2, phase=1.3)),
    ((PLUM, ORANGE), dict(r=3.0, a=42, y=7.5, turns=-1, bob=1.2, bobs=1, phase=2.1)),
    ((PLUM, ORANGE), dict(r=7.0, a=90, y=13.5, turns=1, bob=2.5, bobs=1, phase=0.7)),
    ((GREEN, BLUE), dict(r=7.0, a=-90, y=12.5, turns=1, bob=2.0, bobs=2, phase=3.0)),
    ((GREEN, BLUE), dict(r=5.5, a=65, y=18.5, turns=-2, bob=1.0, bobs=1, phase=0.4)),
    ((CYAN, RED), dict(r=5.0, a=-53, y=16.5, turns=2, bob=1.5, bobs=1, phase=2.6)),
    ((CYAN, RED), dict(r=2.0, a=0, y=19.5, turns=-1, bob=1.0, bobs=2, phase=1.7)),
]
SPARKS = [(16.5, 5.0, -2.0, 0.0), (8.5, 5.8, 3.0, 0.3), (18.5, 9.8, 2.0, 0.55), (5.5, 10.6, 1.0, 0.8),
          (12.5, 10.4, -5.0, 0.15), (14.5, 11.6, 4.0, 0.65), (7.5, 13.6, -3.0, 0.45), (16.5, 15.6, 1.5, 0.9),
          (13.5, 16.8, -4.0, 0.25), (8.5, 20.4, 2.5, 0.7), (10.0, 8.0, -3.5, 0.4), (19.0, 18.0, -2.0, 0.1),
          (4.8, 16.5, -1.5, 0.6), (15.0, 20.0, -2.5, 0.85)]  # (x, y, depth, when it flashes in the loop)


def flight(bug: dict, t: float) -> Vector:
    """Where a bug is at time t (0 to 1 round the loop), kept clear of the glass."""
    w = 2 * math.pi * t
    y = bug["y"] + bug["bob"] * math.sin(bug["bobs"] * w + bug["phase"]) - bug["bob"] * math.sin(bug["phase"])
    y = min(max(y, 6.8), 20.4)
    r = min(bug["r"] + 0.8 * math.sin(2 * w + bug["phase"]) - 0.8 * math.sin(bug["phase"]), inner(y) - 1.7)
    a = math.radians(bug["a"]) + bug["turns"] * w
    return world(12 + r * math.sin(a), y, r * math.cos(a))


def bugs(camera) -> list:
    """Each bug: a round glowing body that always turns its face to the camera, so its wings stay either side of it as
    they were drawn, and two wings buzzing."""
    made = []
    for n, ((wing, body), path) in enumerate(BUGS):
        verts, faces = sphere((1.0, 1.0, 0.95))
        bug = make(f"bug_{n}", verts, faces, [body] * len(faces))
        turn = bug.constraints.new("COPY_ROTATION")
        turn.target, turn.use_x, turn.use_y = camera, False, False
        wings = []
        for side in (-1, 1):
            verts, faces = sphere((0.62, 0.3, 0.55), 12, 8)
            wings.append(make(f"bug_{n}_wing", verts, faces, [wing] * len(faces),
                              at=Vector((side * 1.35, 0.15, 0.45)) * S, parent=bug))
        made.append((bug, wings, path))
    return made


def sparks() -> list:
    made = []
    for n, (x, y, depth, when) in enumerate(SPARKS):
        verts = [Vector(v) * 0.5 * S for v in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1.3), (0, 0, -1.3))]
        faces = [[0, 2, 4], [2, 1, 4], [1, 3, 4], [3, 0, 4], [2, 0, 5], [1, 2, 5], [3, 1, 5], [0, 3, 5]]
        made.append((make(f"spark_{n}", verts, faces, [WHITE] * 8, at=world(x, y, depth)), when))
    return made


def animate(scene, flying: list, twinkling: list) -> None:
    """One loop: the bugs fly round, their wings buzz (four frames a beat), the sparks twinkle in turn."""
    for f in range(FRAMES + 1):
        t = f / FRAMES
        for n, (bug, wings, path) in enumerate(flying):
            bug.location = flight(path, t)
            bug.keyframe_insert("location", frame=f)
            beat = (f + n) % 4
            for wing in wings:
                wing.scale = (1.0, 1.0, (1.0, 0.75, 0.4, 0.75)[beat])
                wing.keyframe_insert("scale", frame=f)
        for spark, when in twinkling:
            glint = math.cos(2 * math.pi * (t - when))  # each flashes once a loop and goes out for a moment
            spark.scale = (1.4 if glint > 0.93 else 0.001 if glint < -0.95 else 0.8,) * 3
            spark.keyframe_insert("scale", frame=f)
    for obj in bpy.data.objects:
        if obj.animation_data and obj.animation_data.action:
            for curve in obj.animation_data.action.fcurves if hasattr(obj.animation_data.action, "fcurves") else []:
                for key in curve.keyframe_points:
                    key.interpolation = "LINEAR"


# -- building and rendering ----------------------------------------------------------------------------------------

def aim(cam, yaw: float) -> None:
    """The camera turned `yaw` degrees round the jar, looking down at it by ELEVATION, the jar in the middle."""
    a, e = math.radians(yaw), math.radians(ELEVATION)
    centre = world(12, MIDDLE)
    cam.location = centre + Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e))) * 10
    cam.rotation_euler = (math.pi / 2 - e, 0, a)
    cam.data.ortho_scale = SPAN * S


SEE_THROUGH = 0.15  # how much of the glass is glass: the rest lets you straight through


def glass_material():
    """Clear glass, for the .blend and the .glb: mostly see-through (EEVEE can't see through glass that only
    transmits: it shows the sky in it, not the bugs), and glass for the rest, which lets light through, bends it a
    little and catches a shine, faintly blue. Cycles makes it real glass; Solid view sees through it by its viewport
    colour. (The frames leave the glass out and draw its outline instead: see reduce_jar.py.)"""
    mat = bpy.data.materials.new(f"{TAG} glass")
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = (0.86, 0.92, 1.0, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.02
    bsdf.inputs["IOR"].default_value = 1.45
    bsdf.inputs["Transmission Weight"].default_value = 1.0
    bsdf.inputs["Alpha"].default_value = SEE_THROUGH
    links.new(bsdf.outputs[0], nodes.new("ShaderNodeOutputMaterial").inputs["Surface"])
    mat.diffuse_color = (*kit.linear(PALE), SEE_THROUGH)
    if hasattr(mat, "surface_render_method"):
        mat.surface_render_method = "BLENDED"
    return mat


def build() -> dict:
    scene = bpy.context.scene
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
    scene.name = SCENE
    scene.render.fps = kit.FPS
    scene.frame_start, scene.frame_end = 0, FRAMES - 1
    cam = bpy.data.objects.new(f"{TAG}_camera", bpy.data.cameras.new(f"{TAG}_camera"))
    cam.data.type = "ORTHO"
    scene.collection.objects.link(cam)
    scene.camera = cam
    aim(cam, 0)
    lid = lathe("lid", LID, lambda y: "lid rim" if 1.3 <= y <= 3.0 else "lid")
    glass = lathe("glass", GLASS, lambda y: PALE)
    glass.data.materials.clear()
    glass.data.materials.append(glass_material())
    wall = glass.modifiers.new("wall", "SOLIDIFY")  # a jar's thin wall, thickened inward so its outside stays put
    wall.thickness, wall.offset, wall.use_even_offset = 0.4 * S, -1.0, True
    # To look at it in Blender: a sun, and a grey sky to shine in the glass. (The frames' flat colours ignore them.)
    sun = bpy.data.objects.new(f"{TAG}_sun", bpy.data.lights.new(f"{TAG}_sun", "SUN"))
    sun.data.energy = 3.0
    sun.rotation_euler = (math.radians(50), 0, math.radians(-30))
    scene.collection.objects.link(sun)
    scene.world = scene.world or bpy.data.worlds.new(f"{TAG}_sky")
    scene.world.use_nodes = True
    scene.world.node_tree.nodes["Background"].inputs[0].default_value = (0.3, 0.3, 0.34, 1.0)
    flying, twinkling = bugs(cam), sparks()
    animate(scene, flying, twinkling)
    scene.frame_set(0)
    toon(False)
    glb = OUT / "jar_o_light.glb"
    OUT.mkdir(exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=str(glb), export_format="GLB", use_active_scene=True, export_animations=True,
                              export_force_sampling=True, export_yup=True, export_apply=True)  # (the glass's wall)
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT / "jar_o_light.blend"))
    (OUT / "jar_mesh.json").write_text(json.dumps({"shades": SHADES, "heavier": HEAVIER, "outline": SLATE,
                                                   "lit_outline": PALE}))
    return {"objects": len(bpy.data.objects), "lid": len(lid.data.polygons), "glass": len(glass.data.polygons),
            "glb_bytes": glb.stat().st_size}


def setup(size: int = 256):
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
    return scene, scene.camera


def show_glass(on: bool) -> None:
    """The glass alone, flat (its outline is all the frames want of it), or everything but the glass."""
    for obj in bpy.data.objects:
        if obj.type == "MESH":
            obj.hide_render = (obj.name != "glass") if on else (obj.name == "glass")
    glass = bpy.data.objects["glass"]
    mat = glass.data.materials[0]
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    out = next(n for n in nodes if n.type == "OUTPUT_MATERIAL")
    if on:
        flat = nodes.get("flat") or nodes.new("ShaderNodeEmission")
        flat.name = "flat"
        links.new(flat.outputs[0], out.inputs["Surface"])
        if hasattr(mat, "surface_render_method"):
            mat.surface_render_method = "DITHERED"


def render_frames(turns: list | None = None) -> dict:
    scene, cam = setup()
    show_glass(True)
    aim(cam, 0)
    scene.frame_set(0)
    scene.render.filepath = str(OUT / "glass.png")
    bpy.ops.render.render(write_still=True, scene=scene.name)
    show_glass(False)
    turns = turns if turns is not None else list(range(DIRECTIONS))
    for d in turns:
        aim(cam, 360 * d / DIRECTIONS)
        scene.render.filepath = str(OUT / "frames_hd" / "Idle" / str(d)) + "/"
        bpy.ops.render.render(animation=True, scene=scene.name)
    return {"turns": len(turns), "frames": FRAMES, "folder": str(OUT / "frames_hd")}


def test_frames(*frames: str) -> dict:
    """A few frames from the front and a quarter turn round: jar_o_light/test/<turn>_<frame>.png."""
    scene, cam = setup()
    show_glass(False)
    paths = []
    for d in (0, DIRECTIONS // 8):
        aim(cam, 360 * d / DIRECTIONS)
        for f in frames:
            scene.frame_set(int(f))
            scene.render.filepath = str(OUT / "test" / f"{d}_{int(f):02d}.png")
            bpy.ops.render.render(write_still=True, scene=scene.name)
            paths.append(scene.render.filepath)
    return {"test": paths}


# -- for the game to draw live -------------------------------------------------------------------------------------

LIVE = HERE.parents[1] / "src" / "ptg" / "data" / "models" / "jar_o_light.json"


def live() -> dict:
    """The jar for the game to draw itself, turning as you watch (ptg/model3d.py): coarser than the frames' (its lid
    and glass turned in 40 sides, its bugs' bodies and wings in fewer), with its bugs' flights and wing beats and the
    sparks' flashes baked a frame at a time from the .blend's animation. In pixels: x to the right, y up from the floor,
    z toward the front."""
    scene = bpy.data.scenes[SCENE]

    def px(v) -> list:  # Blender's metres (x right, y away, z up) -> the model's pixels (x right, y up, z to the front)
        return [round(v.x / S, 3), round(v.z / S, 3), round(-v.y / S, 3)]

    def merged(obj):  # the poles of its turned and round shapes made one point each, its faces still turned out
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bm.to_mesh(obj.data)
        bm.free()
        return obj

    paints: dict[str, dict] = {}

    def paint(name: str) -> str:
        """A paint by name, noted for the model: lit or shaded by the light, by which way it faces (the lid's), or
        always its own colour (the glowing bugs and sparks)."""
        if name in LID_PAINT:
            lit, shade, square = LID_PAINT[name]
            paints[name] = {"lit": lit, "shade": shade, "rule": "facing", "square": square}
        else:
            paints[name] = {"lit": name, "shade": SHADES[name], "rule": "flat" if SHADES[name] == name else "light"}
        return name

    def shape(obj, colour: str | None = None) -> dict:
        """Its points (about its own middle) and faces, and each face's paint: its own, or all `colour`."""
        names = [m.name.removeprefix(f"{TAG} ") for m in obj.data.materials]
        return {"verts": [px(v.co) for v in obj.data.vertices], "faces": [list(p.vertices) for p in obj.data.polygons],
                "paint": [paint(colour or names[p.material_index]) for p in obj.data.polygons]}

    lid = merged(lathe("lid live", LID, lambda y: "lid rim" if 1.3 <= y <= 3.0 else "lid", sides=40))
    glass = merged(lathe("glass live", GLASS, lambda y: PALE, sides=40))
    body = merged(make("body live", *sphere((1.0, 1.0, 0.95), 10, 6), [GREEN] * 60))
    wing = merged(make("wing live", *sphere((0.62, 0.3, 0.55), 8, 5), [GREEN] * 40))
    parts = [{"name": "lid", **shape(lid)}, {"name": "glass", "outline": True, **shape(glass)}]
    bugs = [bpy.data.objects[f"bug_{n}"] for n in range(len(BUGS))]
    wings = [sorted(bug.children, key=lambda c: c.location.x) for bug in bugs]
    sparks = sorted((o for o in bpy.data.objects if o.name.startswith("spark_")), key=lambda o: int(o.name[6:]))
    paths, beats, flashes = [[] for _ in bugs], [[[], []] for _ in bugs], [[] for _ in sparks]
    for f in range(FRAMES):  # the animation, a frame at a time
        scene.frame_set(f)
        for n, bug in enumerate(bugs):
            paths[n].append(px(bug.location))
            for side, child in enumerate(wings[n]):
                beats[n][side].append([round(child.scale.x, 3), round(child.scale.z, 3), round(child.scale.y, 3)])
        for n, spark in enumerate(sparks):
            flashes[n].append(round(spark.scale.x, 3))
    for n, ((wing_colour, body_colour), _) in enumerate(BUGS):
        parts.append({"name": bugs[n].name, "billboard": True, "path": paths[n], **shape(body, body_colour)})
        for side, child in enumerate(wings[n]):
            parts.append({"name": f"{bugs[n].name}_wing_{'lr'[side]}", "parent": bugs[n].name, "at": px(child.location),
                          "scales": beats[n][side], **shape(wing, wing_colour)})
    for n, spark in enumerate(sparks):
        parts.append({"name": spark.name, "spark": True, "at": px(spark.location), "sizes": flashes[n],
                      "paint": paint(WHITE)})
    light = kit.LIGHT
    model = {
        "name": "Jar o' Light", "frames": FRAMES, "fps": kit.FPS, "span": SPAN, "pitch": ELEVATION,
        "centre": [0, kit.GROUND - MIDDLE, 0],  # what it turns about and the view centres on: the jar's middle
        "light": [round(light.x, 3), round(light.y, 3), round(-light.z, 3)], "lit_from": kit.LIT_FROM,
        "outline": {"lit": PALE, "shade": SLATE, "upper": 0.62},
        "paints": paints, "parts": parts,
    }
    LIVE.parent.mkdir(parents=True, exist_ok=True)
    LIVE.write_text(json.dumps(model, separators=(",", ":")))
    return {"model": str(LIVE), "kb": LIVE.stat().st_size // 1024, "parts": len(parts),
            "faces": sum(len(p.get("faces", [])) for p in parts)}


def main(task: str, *args) -> dict:
    if task == "build":
        return build()
    if task == "frames":
        return render_frames([int(a) for a in args] or None)
    if task == "test":
        return test_frames(*args)
    if task == "live":
        return live()
    raise SystemExit(f"unknown task {task!r}: build, frames, test or live")


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else ["build"]
    print("RESULT", json.dumps(main(*argv)))
