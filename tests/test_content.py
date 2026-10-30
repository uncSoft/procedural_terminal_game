import pytest

from ptg.content import ContentError, _read, build_content


def edited(file: str, old: str, new: str):
    """A reader that serves the shipped data with one edit applied."""
    def read(name: str) -> str:
        text = _read(name)
        if name == file:
            assert old in text, f"{old!r} isn't in {file}"
            return text.replace(old, new, 1)
        return text
    return read


@pytest.mark.parametrize("file,old,new,message", [
    ("monsters.toml", "hp = 8\n", "hpp = 8\n", "[monster.goblin]: unknown field 'hpp' (did you mean 'hp'?)"),
    ("monsters.toml", "hp = 5\n", 'hp = "five"\n', "[monster.giant_rat]: hp must be a whole number above 0"),
    ("monsters.toml", 'damage = "1d6"\nxp = 10', 'damage = "lots"\nxp = 10', "damage must be dice like 1d6"),
    ("monsters.toml", "[monster.goblin]", "[monstr.goblin]", "unknown section [monstr] (did you mean 'monster'?)"),
    ("items.toml", 'kind = "weapon"\ndamage = "1d6"', 'kind = "sword"\ndamage = "1d6"', "kind must be weapon, armor"),
    ("items.toml", 'damage = "1d6"\ntier = 0', "tier = 0", "a weapon needs damage"),
    ("perks.toml", 'name = "Brawler"', 'name = "Brawler', "perks.toml: Illegal character"),
    ("themes.toml", 'boss = "goblin_king"', 'boss = "goblin_emperor"', "unknown boss 'goblin_emperor'"),
    ("themes.toml", 'boss = "goblin_king"\n', "", "theme goblin_warren: unknown boss ''"),  # (a floor in a run)
    ("themes.toml", 'goal = "Dethrone the Goblin King."\n', "", "theme goblin_warren: a floor in a run needs a goal"),
    ("monsters.toml", "[monster.goblin]\n", '[monster.goblin]\ndungeons = ["sunken_crypts"]\n',
     "[monster.goblin]: unknown dungeon 'sunken_crypts' (did you mean 'sunken_crypt'?)"),
    ("tags.toml", 'cauldron = ["heavy", "fire", "food"]', 'cauldron = "heavy"', "tags.toml [keywords] cauldron"),
])
def test_bad_edits_are_explained(file, old, new, message):
    with pytest.raises(ContentError) as error:
        build_content(edited(file, old, new))
    assert message in str(error.value)


def test_every_problem_is_reported_at_once():
    def read(name: str) -> str:
        text = _read(name)
        if name == "monsters.toml":
            text = text.replace("hp = 8\n", "hpp = 8\n", 1).replace("hp = 5\n", 'hp = "five"\n', 1)
        return text
    with pytest.raises(ContentError) as error:
        build_content(read)
    assert "goblin" in str(error.value) and "giant_rat" in str(error.value)


def test_valid_edits_still_load():
    content = build_content(edited("monsters.toml", "hp = 8\n", "hp = 1\n"))
    assert content.monster("goblin").hp == 1


@pytest.mark.parametrize("old,new,message", [
    ("meet = \"WOAH", "meeet = \"WOAH", "dialogue.toml [lucky_lenny]: unknown moment 'meeet' (did you mean 'meet'?)"),
    ("[king_mouse]", "[king_mice]", "dialogue.toml [king_mice]: there's no monster 'king_mice' in monsters.toml"),
    ('lying = "You found it!', 'lying = "You found it, {player}!', "lying has a blank the game can't fill, {player}"),
    ('missing = "My tooth', 'missing = 7\nx = "My tooth', "missing must be a line in quotes, or a list of them"),
])
def test_bad_lines_are_explained(old, new, message):
    """The characters' lines (dialogue.toml) are checked like the rest of the data: a typo says where it is."""
    with pytest.raises(ContentError) as error:
        build_content(edited("dialogue.toml", old, new))
    assert message in str(error.value)


def test_the_lines_load_one_or_a_list():
    content = build_content()
    lenny = content.dialogue["lucky_lenny"]
    assert len(lenny["meet"]) == 1 and len(lenny["point_room"]) == 3 and "{place}" in lenny["point_room"][0]


def test_a_floor_below_any_run_may_wait_for_its_boss():
    """A floor still being made, below the deepest a run goes (models.DEEPEST), loads with its rooms and its look but
    not yet its monsters or its boss: waiting. One a run can reach needs them all."""
    from ptg.models import DEEPEST

    themes = _read("themes.toml")
    deeper = themes + ('\n[[theme]]\nkey = "deeper"\nname = "Deeper Still"\nfloor = %d\nblurb = "Darker."\n'
                       'archetypes = ["dark_hollow"]\nmonster_tags = ["nothing_yet"]\n' % (DEEPEST + 1))
    content = build_content(lambda name: deeper if name == "themes.toml" else _read(name))
    assert not content.themes["deeper"].boss
    reachable = deeper.replace(f"floor = {DEEPEST + 1}", f"floor = {DEEPEST}")
    with pytest.raises(ContentError, match="deeper: a floor in a run needs a goal"):
        build_content(lambda name: reachable if name == "themes.toml" else _read(name))


def test_the_underbloom_is_a_runs_fifth_floor_once_youve_won():
    """The Underbloom (floor 5) is below a run's four floors until you've beaten Serpentis once (meta.floors_for);
    then a run goes on down to it, its boss and its key as any floor's."""
    from ptg.models import DEEPEST, FLOORS
    from ptg.world import generate

    content = build_content()
    underbloom = content.themes["underbloom"]
    assert underbloom.floor == DEEPEST > FLOORS
    assert (underbloom.boss, underbloom.key_item, underbloom.boss_room) == ("humongous_fungus", "glowcap_key",
                                                                             "spore_bed")
    assert all("underbloom" not in generate(seed, content=content).themes for seed in range(10))
    assert all(generate(seed, content=content, floors=DEEPEST).themes[-1] == "underbloom" for seed in range(10))
