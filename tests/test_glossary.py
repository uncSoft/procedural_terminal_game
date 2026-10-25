from conftest import put_monster
from ptg.config import Config
from ptg.game import Game
from ptg.glossary import Lexicon, build
from ptg.ui.app import PTGApp
from ptg.ui.game_screen import GameScreen
from ptg.ui.panels import InfoScreen
from ptg.ui.widgets import StoryLine, highlight
from ptg.world import generate


def found(lexicon: Lexicon, text: str) -> dict[str, str]:
    return {text[s:e].lower(): term.id for s, e, term in lexicon.find(text)}


def test_terms_cover_monsters_items_features_and_rules(content):
    state = generate(1)
    put_monster(state, content, key="giant_rat")
    state.room.items.append("oil_flask")
    feature = state.room.visible_features()[0][1]
    head = feature.name.split()[-1]
    lexicon = Lexicon(build(state, content))
    text = (f"The Giant Rat sniffs the {head}. Two rats watch your Healing Potion and the flask of lamp oil. "
            "A Goblin King is nowhere near. Fate smiles.")
    hits = found(lexicon, text)
    assert hits["giant rat"] == "monster:giant_rat" and hits["rats"] == "monster:giant_rat"
    assert "goblin king" not in hits  # (not here, not on the floor, never seen: only a name)
    assert hits[head.lower()].startswith("feature:")
    assert hits["healing potion"] == "item:healing_potion"
    assert hits["flask of lamp oil"] == "item:oil_flask"
    assert found(Lexicon(build(state, content, {"goblin_king": {}})), text)["goblin king"] == "monster:goblin_king"
    assert hits["fate"] == "rule:fate"


def test_a_monster_is_not_found_inside_a_place_name(content):
    """'Goblin' in 'The Goblin Warren' was coloured as a monster, and clicking it opened the goblin's card."""
    state = generate(1)
    state.floor = 2
    put_monster(state, content, key="goblin")
    lexicon = Lexicon(build(state, content))
    text = "You go down the stairs to floor 2, The Goblin Warren. A goblin watches."
    spans = [(text[s:e], s) for s, e, _ in lexicon.find(text)]
    assert spans == [("goblin", text.rindex("goblin"))]  # the one watching, not the place


def test_short_names_only_for_things_nearby(content):
    state = generate(1)
    lexicon = Lexicon(build(state, content))
    # "foot" only means the rabbit's foot if you have one; "oil" only if there's oil around.
    assert "foot" not in found(lexicon, "You stub your foot on some oil.")
    state.player.inventory.append("lucky_charm")
    assert found(Lexicon(build(state, content)), "Your rabbit's foot twitches.")["rabbit's foot"] == "item:lucky_charm"


def test_everyday_words_are_not_short_names(content):
    state = generate(1)
    state.room.features[0].name = "a candle stand"
    state.room.features[0].hidden = False
    hits = found(Lexicon(build(state, content)), "You stand by the candle stand.")
    assert list(hits) == ["candle stand"]


def test_matches_whole_words_only(content):
    state = generate(1)
    put_monster(state, content, key="orc")
    hits = found(Lexicon(build(state, content)), "A sorcerer's orchestra plays. The orc listens.")
    assert list(hits) == ["orc"]


def test_highlight_adds_click_and_tooltip_meta(content):
    state = generate(1)
    put_monster(state, content, key="goblin")
    text = highlight("A goblin grins.", Lexicon(build(state, content)))
    spans = [s for s in text.spans if s.style.meta]
    assert len(spans) == 1 and text.plain[spans[0].start:spans[0].end] == "goblin"
    meta = spans[0].style.meta
    assert meta["term"] == "monster:goblin" and "Goblin" in meta["tip"]


async def test_clicking_a_term_opens_its_card(profile):
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        await pilot.pause()
        state = generate(1)
        app.push_screen(GameScreen(Game(state, Config(backend="offline"), None, profile=profile), fresh=False))
        await pilot.pause(0.3)
        screen = app.screen
        line = screen.add_line(highlight("Rest here, or check your Healing Potion.", screen.lexicon()), "narration")
        await pilot.pause(0.1)
        offset = line.render_line(0).text.index("Healing")
        await pilot.hover(line, offset=(offset + 1, 0))
        await pilot.pause(0.1)
        assert isinstance(line, StoryLine) and "restores 8 HP" in str(line.tooltip)
        await pilot.click(line, offset=(offset + 1, 0))
        await pilot.pause(0.3)
        assert isinstance(app.screen, InfoScreen)
        assert app.screen.term_id == "item:healing_potion"


def test_plain_water_is_not_holy_water(content):
    """Carrying a Vial of Holy Water turned every 'water' in the story into its item card (likewise light, stone,
    dice, duck...): an item's short name is never an everyday word on its own; its full name still is."""
    state = generate(1)
    state.player.inventory += ["holy_water", "weighted_dice", "rubber_duck"]
    text = "Water drips into a puddle. You duck, roll the dice, and uncork the Vial of Holy Water."
    hits = found(Lexicon(build(state, content)), text)
    assert hits == {"vial of holy water": "item:holy_water"}
    assert found(Lexicon(build(state, content)), "The holy water hisses.")["holy water"] == "item:holy_water"
