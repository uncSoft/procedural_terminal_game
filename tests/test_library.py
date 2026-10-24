import base64
import importlib.util
import json
import re
import shutil
import tomllib
import zlib
from pathlib import Path

import pytest
from PIL import Image

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


def rows_of(img) -> list[bytes]:
    return [img.crop((0, y, img.width, y + 1)).tobytes() for y in range(img.height)]


def test_one_picture_bobs_with_its_feet_planted():
    """Its idle frame sinks the body a pixel, as the game's own sprites do, and nothing falls off the bottom."""
    rows = ["." * 24] * 4 + ["......" + "a" * 12 + "......"] * 15 + ["....bb" + "." * 12 + "bb...."] * 5
    art = {"w": 24, "h": 24, "palette": ["#e43b44", "#a22633"], "frames": [rows]}
    still, bobbed = decode_art(art)
    feet = [(x, y) for y in range(19, 24) for x in range(24) if still.getpixel((x, y))[3]]
    assert all(bobbed.getpixel(p) == still.getpixel(p) for p in feet)  # the feet (the red shoes) stay put
    assert rows_of(bobbed)[1:19] == rows_of(still)[:18]  # the body sinks
    assert bobbed.getbbox()[1] == still.getbbox()[1] + 1
    tool = importlib.util.spec_from_file_location("build_sprites",
                                                  Path(__file__).parents[1] / "tools" / "build_sprites.py")
    build_sprites = importlib.util.module_from_spec(tool)
    tool.loader.exec_module(build_sprites)
    assert library.bob(still).tobytes() == build_sprites.bob(still).tobytes()  # the same bob as the game's own art
    small = decode_art({"w": 12, "h": 12, "palette": ["#e43b44"], "frames": [["a" * 12] * 12]})
    assert rows_of(small[1])[-2:] == rows_of(small[0])[-2:] and not any(small[1].crop((0, 0, 12, 1)).tobytes())


def test_no_idle_frame_loses_pixels_off_the_bottom():
    """A second frame that's just the first moved down a pixel must have had nothing in its bottom row to lose."""
    for path in sorted((library.data_folder() / "sprites").rglob("*.png")):
        frames = read_frames(path)
        if len(frames) != 2:
            continue
        shifted = Image.new("RGBA", frames[0].size, (0, 0, 0, 0))
        shifted.alpha_composite(frames[0], (0, 1))
        if frames[1].tobytes() == shifted.tobytes():
            assert not any(rows_of(frames[0])[-1][3::4]), f"{path.name} loses its bottom row as it bobs"


def stale_pictures(stored: dict, folder) -> list[str]:
    """The creations whose picture (or small version) in a maker library isn't the game's PNG any more."""
    stale = []
    for kind, entries in (("monster", stored["monsters"]), ("item", stored["items"])):
        for entry in entries:
            picture, small = library.sprite_file(kind, entry["key"], folder), library.small_file(entry["key"], folder)
            if entry["art"] != (encode_art(read_frames(picture)) if picture.is_file() else None):
                stale.append(entry["key"])
            if kind == "item" and entry.get("small") != (encode_art(read_frames(small)) if small.is_file() else None):
                stale.append(f"{entry['key']} (small)")
    return stale


def test_the_maker_page_has_the_pictures_the_game_has():
    """docs/maker/library.json holds each creation's picture as its PNG is now. The maker sends a stale one back with
    any change to that creation, and the import saves it over the PNG: after changing a sprite, run `ptg export`."""
    stored = json.loads((Path(__file__).parents[1] / "docs" / "maker" / "library.json").read_text(encoding="utf-8"))
    assert not stale_pictures(stored, library.data_folder()), "library.json is out of date: run `uv run ptg export`"


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


SAVES = "https://script.example/macros/s/abc/exec"


def fake_saves(*creations):
    """Stands in for the maker's shared library: answers with these saves, numbered in order, newest first."""
    saves = [{**c, "id": f"save{n}", "no": n, "saved": f"2026-10-22T10:0{n}:00.000Z"}
             for n, c in enumerate(creations, 1)]
    asked = []

    def get(url):
        asked.append(url)
        return {"creations": [dict(s) for s in reversed(saves)]}
    return get, asked


def spoon(**fields) -> dict:
    return {"v": 1, "type": "item", "by": "Ada", "made": "2026-10-23", "art": drawing("#feae34"),
            "fields": {"name": "Spoon of Destiny", "kind": "weapon", "damage": "1d8", "tier": 1, "tags": ["shiny"],
                       **fields}}


def test_a_new_picture_keeps_what_the_game_gave_an_item(data):
    """The maker knows an item's look and numbers; its powers and where it's found live in the game's data only."""
    edit = {"v": 1, "type": "item", "by": "JT", "made": "2026-10-23", "base": "oil_flask", "art": drawing("#f77622"),
            "fields": {"name": "Flask of Lamp Oil", "kind": "trinket", "tier": 1, "tags": ["fire", "liquid"]}}
    apply([edit], data)
    item = tomllib.loads((data / "items.toml").read_text(encoding="utf-8"))["item"]["oil_flask"]
    assert item["powers"] == ["throw"] and item["damage"] == "2d4" and item["tags"] == ["fire", "liquid"]


def page_fields(kind: str) -> list[str]:
    """The fields the maker page sends back for a monster or an item (its MONSTER_FIELDS and ITEM_FIELDS)."""
    page = (library.maker_folder() / "index.html").read_text(encoding="utf-8")
    return re.findall(r'"(\w+)"', re.search(rf"const {kind.upper()}_FIELDS = \[(.*?)\];", page).group(1))


def test_sending_anything_back_from_the_library_unchanged_changes_nothing(data):
    """Touching up art starts from the maker's library: an entry sent back as it is keeps everything the maker
    doesn't know about (Baby Joey's tricks, the Unusual Butter's stats, every power and `found`), in its place."""
    before = {name: (data / name).read_text(encoding="utf-8") for name in ("monsters.toml", "items.toml", "art.txt")}
    stored = export_library(data)
    edits = []
    for kind, shelf in (("monster", "monsters"), ("item", "items")):
        for entry in stored[shelf]:
            fields = {k: entry["fields"][k] for k in page_fields(kind) if k in entry["fields"]}
            edit = {"v": 1, "type": kind, "base": entry["key"], "fields": fields, "art": entry["art"],
                    "by": entry.get("by", ""), "made": entry.get("made", "")}
            if entry.get("small"):
                edit["small"] = entry["small"]
            edits.append(edit)
    messages = [m for m in apply(edits, data) if not m.startswith("Colours:")]  # (notes on colours aside)
    for edit, message in zip(edits, messages, strict=True):  # each called by its own name
        assert message.startswith(f"Updated {edit['type']} {edit['fields']['name']} ({edit['base']})"), message
    assert {name: (data / name).read_text(encoding="utf-8") for name in before} == before
    assert export_library(data)["items"] == stored["items"] and export_library(data)["monsters"] == stored["monsters"]


def test_an_items_stats_are_written_as_a_table(data):
    edit = {"v": 1, "type": "item", "base": "unusual_butter", "art": drawing("#feae34"),
            "fields": {"name": "Unusual Butter", "kind": "trinket", "tier": 3, "desc": "Even more exotic."}}
    apply([edit], data)
    assert "stats = {might = 1, agility = 1, wits = 1, max_hp = 5}" in (data / "items.toml").read_text()
    butter = load(data).items["unusual_butter"]
    assert butter.desc == "Even more exotic." and butter.found == ["chest", "secret"]


def files(folder):
    return {p.name: p.read_bytes() for p in folder.rglob("*") if p.is_file()}


def test_saves_waiting_for_the_game_are_listed_by_number(data):
    from ptg.library import import_saves

    edit = monster(name="Goblin", tags=["goblinoid"], weak=["shiny"])
    edit["base"] = "goblin"
    get, asked = fake_saves(monster(name="Bog Cantor"), spoon(), edit)
    before = files(data)
    assert import_saves(SAVES, folder=data, get=get) == [
        "Saved in the maker, not in the game yet:",
        "  #1  Monster Bog Cantor by Lily (2026-10-22): tier 1, 8 HP, 1d6",
        "  #2  Item Spoon of Destiny by Ada (2026-10-23): weapon, tier 1, 1d8",
        "  #3  Monster Goblin by Lily (2026-10-22): tier 1, 8 HP, 1d6, a change to goblin",
        "Bring some in with: uv run ptg import --saves 1 2",
    ]
    assert asked == [SAVES] and files(data) == before  # only looking


def test_picked_saves_join_the_game_and_stop_waiting(data):
    from ptg.library import import_saves

    get, _ = fake_saves(monster(name="Bog Cantor"), spoon())
    assert import_saves(SAVES, [2], folder=data, get=get) == \
        ["#2: Added item Spoon of Destiny (spoon_of_destiny) by Ada."]
    assert "spoon_of_destiny" in load(data).items
    listed = import_saves(SAVES, folder=data, get=get)
    assert listed[1].startswith("  #1  Monster Bog Cantor") and "(1 more is in the game already.)" in listed
    assert import_saves(SAVES, [2], folder=data, get=get) == \
        ["#2 Item Spoon of Destiny by Ada: it's in the game already."]
    assert "spoon_of_destiny_2" not in load(data).items  # picking it twice doesn't add it twice
    assert import_saves(SAVES, [1], folder=data, get=get) == \
        ["#1: Added monster Bog Cantor (bog_cantor) by Lily, lives in The Sunken Crypt."]
    assert import_saves(SAVES, folder=data, get=get) == \
        ["Nothing waiting: everything saved in the maker is in the game already."]


def test_saves_that_cant_come_in_dont_stop_the_rest(data):
    from ptg.library import import_saves

    get, _ = fake_saves(monster(name="Broken", damage="lots"), monster(name="Bog Cantor"))
    lines = import_saves(SAVES, [3, 1, 2], folder=data, get=get)
    assert lines[0] == "#3: there's no save with that number."
    assert lines[1].startswith("#1 Monster Broken by Lily: couldn't import it: the game wouldn't load")
    assert lines[2].startswith("#2: Added monster Bog Cantor (bog_cantor)")


def test_a_saves_dry_run_writes_nothing(data):
    from ptg.library import import_saves

    get, _ = fake_saves(monster(name="Bog Cantor"))
    before = files(data)
    assert import_saves(SAVES, [1], dry_run=True, folder=data, get=get) == [
        "#1: Added monster Bog Cantor (bog_cantor) by Lily, lives in The Sunken Crypt.", "(dry run: nothing written)"]
    assert files(data) == before


def test_a_shared_library_without_numbers_is_counted_oldest_first(data):
    from ptg.library import import_saves, saved_creations

    newer = {**monster(name="Second"), "saved": "2026-10-23T09:00:00Z"}
    older = {**monster(name="First"), "saved": "2026-10-22T09:00:00Z"}
    junk = [{"type": "spell"}, "nonsense", {"type": "monster", "fields": "not a dict"}]
    creations = saved_creations(SAVES, get=lambda url: {"creations": [newer, *junk, older]})
    assert [(c["no"], c["fields"]["name"]) for c in creations] == [(1, "First"), (2, "Second")]
    assert saved_creations(SAVES, get=lambda url: {"something": "else"}) == []
    assert import_saves(SAVES, folder=data, get=lambda url: {"creations": []}) == \
        ["Nothing's been saved in the maker yet."]


def test_the_shared_library_is_found_in_the_makers_config(tmp_path, monkeypatch):
    from ptg.library import saves_url

    assert saves_url("https://given.example") == "https://given.example"
    maker = tmp_path / "maker"
    maker.mkdir()
    monkeypatch.setattr(library, "maker_folder", lambda: maker)
    with pytest.raises(ValueError, match="no shared library"):
        saves_url()
    (maker / "config.json").write_text(json.dumps({"repo": "me/game", "saves": {"url": ""}}))
    with pytest.raises(ValueError, match="saves.url"):
        saves_url()
    (maker / "config.json").write_text(json.dumps({"saves": {"url": SAVES}}))
    assert saves_url() == SAVES


def test_the_cli_lists_and_imports_saves(tmp_path, monkeypatch, capsys):
    from ptg.library import saved_creations

    maker = tmp_path / "maker"
    maker.mkdir()
    (maker / "config.json").write_text(json.dumps({"saves": {"url": SAVES}}))
    monkeypatch.setattr(library, "maker_folder", lambda: maker)
    get, asked = fake_saves(monster(name="Quizzical Newt"))
    monkeypatch.setattr(library, "saved_creations", lambda url, _=None: saved_creations(url, get))
    assert library.main(["import", "--saves"]) == 0
    assert "  #1  Monster Quizzical Newt by Lily" in capsys.readouterr().out and asked == [SAVES]
    assert library.main(["import", "--saves", "#1", "--dry-run", "--url", "https://elsewhere.example"]) == 0
    out = capsys.readouterr().out
    assert "#1: Added monster Quizzical Newt" in out and "(dry run" in out and asked[-1] == "https://elsewhere.example"
    monkeypatch.setattr(library, "maker_folder", lambda: None)
    assert library.main(["import", "--saves"]) == 1
    assert "no shared library" in capsys.readouterr().out


def small_drawing(colour: str = "#feae34") -> dict:
    rows = ["." * 12] * 3 + ["...aaaaaa..."] * 6 + ["." * 12] * 3
    return {"w": 12, "h": 12, "palette": [colour], "frames": [rows]}


def test_an_item_can_bring_its_small_version(data):
    item = spoon()
    item["small"] = small_drawing()
    assert apply([item], data)[0] == ("Added item Spoon of Destiny (spoon_of_destiny) by Ada, with a small version "
                                      "drawn by hand.")
    small = read_frames(library.small_file("spoon_of_destiny", data))
    assert small[0].size == (12, 12) and len(small) == 2  # one picture gets the bob, like the big one
    library.small_file("stale_bread", data).unlink()  # one that's only ever been halved
    lib = export_library(data)
    entry = next(i for i in lib["items"] if i["key"] == "spoon_of_destiny")
    assert entry["small"]["w"] == 12 and decode_art(entry["small"])[0].tobytes() == small[0].tobytes()
    assert "small" not in next(i for i in lib["items"] if i["key"] == "stale_bread")


def test_a_small_version_must_be_small(data):
    item = spoon()
    item["small"] = drawing()  # 24 across
    with pytest.raises(ValueError, match="should be 12x12"):
        apply([item], data)
    assert not library.small_file("spoon_of_destiny", data).exists()


def test_a_new_picture_without_a_small_version_retires_the_old_one(data):
    with_small = spoon()
    with_small["small"] = small_drawing()
    apply([with_small], data)
    numbers_only = spoon(damage="1d10")  # the same picture: the small version still fits
    numbers_only["base"] = "spoon_of_destiny"
    apply([numbers_only], data)
    assert library.small_file("spoon_of_destiny", data).exists()
    repainted = spoon()
    repainted["base"], repainted["art"] = "spoon_of_destiny", drawing("#e43b44")
    message = apply([repainted], data)[0]
    assert "small version was drawn for the old picture" in message
    assert not library.small_file("spoon_of_destiny", data).exists()


def test_monsters_dont_get_small_versions(data):
    creature = monster()
    creature["small"] = small_drawing()
    apply([creature], data)
    assert not list((data / "sprites" / "small").glob("*squeaks*"))


def test_colours_from_outside_the_makers_palette_are_pointed_out(data):
    """A custom colour still shows, but each one is another colour for the game's effects and the terminal."""
    item = spoon()
    item["art"] = drawing("#9e9e9e")  # a custom grey, not Endesga's
    item["small"] = small_drawing("#f9eeb4")
    added, note = apply([item], data)[:2]
    assert note.startswith("Colours:") and "2 colours from outside the maker's palette (#9e9e9e, #f9eeb4)" in note
    assert added.startswith("Added") and "palette" not in added  # (the maker's thank-you quotes only this one)
    assert (data / "sprites" / "item_spoon_of_destiny.png").is_file()  # it's only a warning
    assert not any("palette" in m for m in apply([spoon(damage="1d10")], data))  # all Endesga: nothing to say


def test_the_palette_is_the_makers():
    page = (library.maker_folder() / "index.html").read_text(encoding="utf-8")
    listed = re.search(r"const PALETTE = \[(.*?)\];", page, re.S).group(1)
    assert tuple(re.findall(r'"(#[0-9a-f]{6})"', listed)) == library.ENDESGA
    picture = decode_art({"w": 8, "h": 8, "palette": ["#181425", "#123456"], "frames": [["ab" * 4] * 8]})
    assert library.off_palette(picture) == ["#123456"]
