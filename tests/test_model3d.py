"""The 3D models the game draws as you watch (ptg/model3d.py), and the window you turn one over in (ui/model_view.py)."""

import hashlib
import json
from importlib import resources

from ptg import model3d
from ptg.config import Config
from ptg.sprites import frames
from ptg.ui.app import PTGApp
from ptg.ui.model_view import ModelScreen, ModelView
from ptg.ui.panels import InventoryScreen
from test_ui import into_a_run


def colours(image) -> set:
    return {rgba for _, rgba in image.getcolors(1 << 16)}


def test_the_jar_draws_in_its_own_colours_from_every_side():
    """Whichever way it's turned, and whatever frame its bugs are at, it's drawn in nothing but its paints and its
    glass's outline, every pixel solid or clear."""
    model = model3d.load("jar_o_light")
    allowed = {p.lit for p in model.paints} | {p.shade for p in model.paints}
    allowed |= {model3d.rgba(model.outline["lit"]), model3d.rgba(model.outline["shade"]), (0, 0, 0, 0)}
    for turn in range(8):
        image = model3d.render(model, frame=turn * 5, yaw=turn * 45, size=64)
        assert image.getbbox(), "nothing drawn"
        assert colours(image) <= allowed


def test_turning_it_turns_it():
    """Turned, its bugs are somewhere else in the picture, but the jar is the same shape: it's round."""
    model = model3d.load("jar_o_light")
    front, side = (model3d.render(model, 0, yaw, size=64) for yaw in (0, 90))
    assert front.tobytes() != side.tobytes()
    assert front.getbbox() == side.getbbox()


def test_a_bigger_picture_has_a_thicker_outline():
    """The glass's outline is a sprite pixel thick, so the picture keeps its look as it grows."""
    model = model3d.load("jar_o_light")
    slate = model3d.rgba(model.outline["shade"])

    def bottom_edge(size: int) -> int:  # rows of slate under the middle of the jar
        image = model3d.render(model, 0, 0, size=size)
        column = [image.getpixel((size // 2, y)) for y in range(size)]
        return sum(1 for rgba in column[size // 2:] if rgba == slate)

    assert bottom_edge(48) == 1 and bottom_edge(96) == 2


async def test_the_pack_turns_the_jar_over():
    """In the pack, t (or the line under its words) opens the jar in a window: it turns on its own, the arrows turn it
    and stop it, and Esc goes back to the pack."""
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        screen.game.state.player.inventory = ["jar_o_light"]
        await pilot.press("f2")
        await pilot.pause(0.3)
        inventory = app.screen
        assert isinstance(inventory, InventoryScreen)
        await pilot.press("right")  # from the sword in hand to the jar
        await pilot.pause(0.1)
        assert "Turn it over" in " ".join(str(b.render()) for b in inventory.query(".inv-verb"))
        await pilot.press("t")
        await pilot.pause(0.3)
        assert isinstance(app.screen, ModelScreen)
        view = app.screen.query_one(ModelView)
        assert view.picture.plain.strip()  # drawn
        turned = view.yaw
        await pilot.pause(0.3)
        assert view.yaw != turned  # turning on its own
        await pilot.press("left")
        stopped = view.yaw
        await pilot.pause(0.3)
        assert not view.spinning and view.yaw == stopped
        await pilot.press("escape")
        await pilot.pause(0.2)
        assert app.screen is inventory


def made_from_sprites() -> list[str]:
    """The items whose models item_model.py made from their sprites (spikes/goblin3d/item_models.toml)."""
    folder = resources.files("ptg") / "data" / model3d.FOLDER
    return sorted(p.name[:-5] for p in folder.iterdir()
                  if p.name.endswith(".json") and "sprite" in json.loads(p.read_text()))


def test_every_item_model_keeps_to_its_sprites_colours():
    """A model made from an item's sprite (a slab, a relief, a turned thing, a jar, or one shaped by hand) is drawn,
    whichever way it's turned, in nothing but its sprite's own colours, every pixel solid or clear."""
    keys = made_from_sprites()
    assert len(keys) > 50
    for key in keys:
        sprite = {rgba[:3] for frame in frames(f"item_{key}") for _, rgba in frame.convert("RGBA").getcolors(1 << 16)
                  if rgba[3] >= 128}
        model = model3d.load(key)
        for turn in range(4):
            image = model3d.render(model, frame=turn * 7, yaw=turn * 95, size=48)
            assert image.getbbox(), key
            drawn = {rgba[:3] for rgba in colours(image) if rgba[3]}
            assert drawn <= sprite, (key, drawn - sprite)
            assert {rgba[3] for rgba in colours(image)} <= {0, 255}, key


def test_every_item_model_is_made_from_its_sprite_as_drawn_now():
    """Each model remembers the sprite it was made from: a sprite drawn again since needs its model made again
    (uv run python spikes/goblin3d/item_model.py <item>)."""
    stale = []
    for key in made_from_sprites():
        drawn = hashlib.sha1((resources.files("ptg") / "data" / "sprites" / f"item_{key}.png").read_bytes())
        if json.loads(model3d.path_of(key).read_text())["sprite"] != drawn.hexdigest()[:12]:
            stale.append(key)
    assert not stale, f"redrawn since their models were made: {stale}"
