"""The character sheet's sums (sheet.py): each stat and roll with where every bonus comes from."""

from ptg import sheet
from ptg.world import generate


def parts(line):
    return {(p.name, p.value, p.item) for p in line.parts}


def test_a_carried_ring_shows_on_the_dodge_and_flee_it_helps_and_says_it_is_cursed(content):
    """A Ring, Probably Important gives +2 to dodge and flee, but the sheet never said so."""
    state = generate(1)
    state.player.inventory.append("a_ring_probably_importan")
    ring = ("A Ring, Probably Important", 2, "a_ring_probably_importan")
    rolls = {line.label: line for line in sheet.roll_lines(state, content)}
    assert ring in parts(rolls["Dodge"]) and ring in parts(rolls["Flee"])
    assert ring not in parts(rolls["Attack"])
    assert rolls["Dodge"].total == state.player.agility + 2
    effect = next(e for e in sheet.carried_effects(state, content) if e.item == "a_ring_probably_importan")
    assert effect.cursed and any("dodge" in said for said in effect.says)


def test_a_stat_is_its_base_plus_what_you_carry(content):
    state = generate(1)
    state.player.inventory.append("lenny_s_bad_tooth")
    from ptg import powers
    powers.settle_stats(state, content)
    might = sheet.stat_line(state, content, "might")
    tooth = next(p for p in might.parts if p.item == "lenny_s_bad_tooth")
    base = next(p for p in might.parts if p.name == "base")
    assert might.total == state.player.might == base.value + tooth.value


def test_defense_and_the_attack_roll_add_up(content):
    state = generate(1)
    state.player.armor = "chain_shirt"
    defense = sheet.defense_line(state, content)
    assert defense.total == sum(p.value for p in defense.parts) == state.player.defense(content)
    attack = next(line for line in sheet.roll_lines(state, content) if line.label == "Attack")
    assert attack.total == state.player.might + state.player.level


def test_a_potion_in_your_pack_is_not_working_on_you(content):
    state = generate(1)
    state.player.inventory = ["healing_potion"]
    assert [e.item for e in sheet.carried_effects(state, content)] == [state.player.weapon]


async def test_the_sheet_links_the_ring_on_the_rolls_it_helps():
    from test_ui import into_a_run
    from ptg.config import Config
    from ptg.ui.app import PTGApp
    from ptg.ui.panels import CharacterScreen, InfoScreen
    from ptg.ui.widgets import StoryLine

    app = PTGApp(Config(backend="offline", player_name="T"), seed=1)
    async with app.run_test(size=(140, 40)) as pilot:
        screen = await into_a_run(app, pilot)
        screen.game.state.player.inventory.append("a_ring_probably_importan")
        await pilot.press("f3")
        await pilot.pause(0.4)
        assert isinstance(app.screen, CharacterScreen)
        terms = set()
        for line in app.screen.query(StoryLine):
            for strip in line.render_lines(line.region.reset_offset):  # (rendered, as clicks see it)
                terms |= {seg.style.meta.get("term") for seg in strip if seg.style and seg.style.meta}
        assert "item:a_ring_probably_importan" in terms
        app.screen.action_lookup("item:a_ring_probably_importan")
        await pilot.pause(0.3)
        assert isinstance(app.screen, InfoScreen)
