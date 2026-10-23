import base64
import json
import shutil
import tomllib
import zlib

import pytest

from ptg import integrity, library
from ptg.content import build_content
from ptg.library import apply, decode_art, encode_art, export_library, read_frames, read_source, replace_section


@pytest.fixture
def data(tmp_path):
    """A copy of the game's data to import into, so the real files are never touched."""
    folder = tmp_path / "data"
    shutil.copytree(library.data_folder(), folder)
    return folder


def link(creation: dict) -> str:
    """The way the maker page packs a creation into a link: raw deflate, then URL-safe base64."""
    squeezer = zlib.compressobj(9, zlib.DEFLATED, -15)
    packed = squeezer.compress(json.dumps(creation).encode()) + squeezer.flush()
    return "https://example.github.io/maker/#c=z" + base64.urlsafe_b64encode(packed).decode().rstrip("=")


def drawing(colour: str = "#e43b44") -> dict:
    rows = ["." * 24] * 6 + ["......" + "a" * 12 + "......"] * 12 + ["." * 24] * 6
    return {"w": 24, "h": 24, "palette": [colour], "frames": [rows]}


def monster(**fields) -> dict:
    base = {"name": "Sir Squeaks", "hp": 8, "defense": 12, "attack": 3, "damage": "1d6", "xp": 10, "tier": 1,
            "tags": ["undead"], "weak": ["fire"], "intelligent": True, "tell": "sneezes ominously"}
    return {"v": 1, "type": "monster", "fields": {**base, **fields}, "art": drawing(), "by": "Lily", "made": "2026-10-22"}


def load(folder):
    return build_content(lambda name: (folder / name).read_text(encoding="utf-8"))


def test_the_library_holds_everything_with_its_art():
    lib = export_library()
    content = load(library.data_folder())
    assert {m["key"] for m in lib["monsters"]} == set(content.monsters)
    assert {i["key"] for i in lib["items"]} == set(content.items)
    goblin = next(m for m in lib["monsters"] if m["key"] == "goblin")
    assert goblin["art"]["w"] == 24 and len(goblin["art"]["frames"]) == 2 and goblin["lives"]
    assert lib["reference"]["monster"]["2"]["hp"] > lib["reference"]["monster"]["1"]["hp"]
    assert "The Sunken Crypt" in lib["kinds"]["undead"]


def test_art_survives_the_trip_to_the_page_and_back():
    frames = read_frames(library.data_folder() / "sprites" / "troll.png")
    again = decode_art(encode_art(frames))
    assert [f.tobytes() for f in again] == [f.tobytes() for f in frames]


def test_a_new_monster_joins_the_game(data):
    messages = apply(read_source(link(monster())), data)
    assert messages[0] == "Added monster Sir Squeaks (sir_squeaks) by Lily, lives in The Sunken Crypt."
    content = load(data)
    squeaks = content.monsters["sir_squeaks"]
    assert (squeaks.tier, squeaks.weak, squeaks.intelligent) == (1, ["fire"], True) and squeaks.art.strip()
    assert "# drawn by Lily (2026-10-22)\n[monster.sir_squeaks]" in (data / "monsters.toml").read_text()
    assert len(read_frames(data / "sprites" / "sir_squeaks.png")) == 2  # one picture gets a bob for free
    assert not integrity.check(data).tampered  # signed: no Hackerman for the grown-up who imported it
    assert apply(read_source(link(monster())), data)[0].startswith("Added monster Sir Squeaks (sir_squeaks_2)")


def test_changing_a_monster_leaves_the_rest_alone(data):
    before = (data / "monsters.toml").read_text()
    art_before = load(data).monsters["goblin"].art
    edit = monster(name="Goblin", tags=["goblinoid"], weak=["shiny"], tell="shrieks louder than before")
    edit["base"] = "goblin"
    assert apply([edit], data)[0].startswith("Updated monster Goblin (goblin) by Lily")
    content = load(data)
    assert content.monsters["goblin"].tell == "shrieks louder than before"
    assert content.monsters["goblin"].art == art_before  # the hand-drawn ASCII art stays
    after = (data / "monsters.toml").read_text()
    assert after.split("[monster.goblin]")[0].rstrip().removesuffix("# drawn by Lily (2026-10-22)").rstrip() == \
        before.split("[monster.goblin]")[0].rstrip()  # everything above it is as it was
    assert after.split("[monster.skeleton]")[1] == before.split("[monster.skeleton]")[1]


def test_a_boss_stays_a_boss(data):
    edit = monster(name="The Goblin King", boss=False)
    edit["base"] = "goblin_king"
    apply([edit], data)
    assert load(data).monsters["goblin_king"].boss


def test_a_new_item_with_art(data):
    item = {"v": 1, "type": "item", "by": "Lily", "art": drawing("#feae34"),
            "fields": {"name": "Spoon of Destiny", "kind": "weapon", "damage": "1d8", "tier": 1, "tags": ["shiny", "sharp"],
                       "desc": "Stirs soup. Stirs trouble."}}
    assert apply([item], data)[0] == "Added item Spoon of Destiny (spoon_of_destiny) by Lily."
    assert load(data).items["spoon_of_destiny"].damage == "1d8"
    assert (data / "sprites" / "item_spoon_of_destiny.png").is_file()


def test_nothing_is_written_when_something_is_wrong(data):
    before = {p.name: p.read_bytes() for p in data.iterdir() if p.is_file()}
    with pytest.raises(ValueError, match="needs a name"):
        apply([monster(name="")], data)
    with pytest.raises(ValueError, match="wouldn't load"):
        apply([monster(damage="lots")], data)  # not dice
    blank = monster()
    blank["art"] = {"w": 24, "h": 24, "palette": [], "frames": [["." * 24] * 24]}
    with pytest.raises(ValueError, match="empty"):
        apply([blank], data)
    assert {p.name: p.read_bytes() for p in data.iterdir() if p.is_file()} == before


def test_links_codes_and_files(tmp_path):
    made = monster()
    code = link(made).split("#c=")[1]
    assert read_source(link(made))[0]["fields"]["name"] == "Sir Squeaks"
    assert read_source(code)[0]["by"] == "Lily"
    plain = "j" + base64.urlsafe_b64encode(json.dumps(made).encode()).decode()  # browsers without compression
    assert read_source(plain)[0]["type"] == "monster"
    saved = tmp_path / "my-creations.ptg.json"
    saved.write_text(json.dumps({"creations": [made, made]}))
    assert len(read_source(str(saved))) == 2
    with pytest.raises(ValueError, match="doesn't look like a link"):
        read_source("not a maker link at all")


def test_sections_are_replaced_in_place():
    text = "# about the file\n\n[monster.a]\nname = \"A\"\n\n# notes on b\n[monster.b]\nname = \"B\"\n"
    out = replace_section(text, "monster", "a", ["# drawn by Lily (2026-10-22)", "[monster.a]", 'name = "Ay"'])
    assert out.startswith("# about the file\n\n# drawn by Lily") and "# notes on b\n[monster.b]" in out
    assert tomllib.loads(out)["monster"] == {"a": {"name": "Ay"}, "b": {"name": "B"}}


def test_the_cli_imports_and_exports(tmp_path, capsys):
    saved = tmp_path / "made.json"
    saved.write_text(json.dumps(monster()))
    assert library.main(["import", str(saved), "--dry-run"]) == 0
    assert "Added monster Sir Squeaks" in capsys.readouterr().out
    target = tmp_path / "library.json"
    assert library.main(["export", str(target)]) == 0 and json.loads(target.read_text())["monsters"]


def fake_gh(issues):
    """Stands in for the GitHub CLI: lists the given issues and records everything else it's asked to do."""
    import subprocess

    calls = []

    def run(argv, **_):
        calls.append(argv)
        out = json.dumps(issues) if argv[:3] == ["gh", "issue", "list"] else ""
        return subprocess.CompletedProcess(argv, 0, out, "")
    return run, calls


def issue(number, title, body, login="pal"):
    return {"number": number, "title": title, "body": body, "author": {"login": login}}


def test_github_submissions_are_imported_credited_and_closed(data):
    from ptg.library import import_github

    anonymous = monster(name="Bog Cantor")
    anonymous["by"] = ""
    body = "**Bog Cantor**\n\n<details>\n\n```ptg-creation\n" + link(anonymous).split("#c=")[1] + "\n```\n</details>"
    run, calls = fake_gh([issue(7, "[maker] Monster: Bog Cantor", body), issue(8, "A bug report", "nothing to see"),
                          issue(9, "[maker] Item: Junk", "no data here", "joker")])
    lines = import_github("me/game", folder=data, run=run)
    assert lines[0] == "#7 Monster: Bog Cantor (from pal): Added monster Bog Cantor (bog_cantor) by pal, lives in The Sunken Crypt."
    assert lines[1].startswith("#9 Item: Junk (from joker): no maker data")
    assert len(lines) == 2  # the bug report isn't a submission
    assert "bog_cantor" in load(data).monsters
    closed = [c for c in calls if c[:3] == ["gh", "issue", "close"]]
    assert [c[3] for c in closed] == ["7"] and "Imported into the game" in closed[0][-1]


def test_a_github_dry_run_closes_nothing(data):
    from ptg.library import import_github

    body = "[Open it](" + link(monster(name="Bog Cantor")) + ")"
    run, calls = fake_gh([issue(3, "[maker] Monster: Bog Cantor", body)])
    lines = import_github("me/game", dry_run=True, folder=data, run=run)
    assert lines[-1].startswith("(dry run") and "bog_cantor" not in load(data).monsters
    assert not [c for c in calls if c[:3] == ["gh", "issue", "close"]]


def test_one_bad_submission_doesnt_stop_the_rest(data):
    from ptg.library import import_github

    good = "```ptg-creation\n" + link(monster(name="Bog Cantor")).split("#c=")[1] + "\n```"
    bad = "```ptg-creation\n" + link(monster(name="Broken", damage="lots")).split("#c=")[1] + "\n```"
    run, _ = fake_gh([issue(1, "[maker] Monster: Broken", bad), issue(2, "[maker] Monster: Bog Cantor", good)])
    lines = import_github("me/game", folder=data, run=run)
    assert "couldn't import it" in lines[0] and "Added monster Bog Cantor" in lines[1]


def test_monsters_can_carry_a_description(data):
    apply([monster(name="Bog Cantor", desc="A toad the size of a pew.")], data)
    assert load(data).monsters["bog_cantor"].desc == "A toad the size of a pew."
