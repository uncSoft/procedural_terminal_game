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
