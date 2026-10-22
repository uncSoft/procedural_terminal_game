import shutil

from ptg import cli, integrity, meta
from ptg.config import Config
from ptg.content import ContentError, load_content
from ptg.game import Game
from ptg.integrity import Report, check, sign
from ptg.world import generate


def test_shipped_data_is_signed():
    report = check()
    assert not report.tampered, (
        "The data files changed without being re-signed: " + "; ".join(report.lines())
        + ". If that was deliberate, run: uv run python -m ptg.integrity --sign")


def test_edits_additions_and_removals_are_noticed(tmp_path):
    folder = tmp_path / "data"
    shutil.copytree(integrity.data_folder(), folder)
    sign(folder)
    assert not check(folder).tampered
    (folder / "monsters.toml").write_text((folder / "monsters.toml").read_text() + "\n# buffed\n")
    (folder / "story" / "my_mod.md").write_text("---\nid: my_mod\nwhen: turn\n---\nHi.\n")
    (folder / "perks.toml").unlink()
    (folder / "sprites" / "goblin.png").write_bytes(b"not really a png")  # custom art doesn't count
    report = check(folder)
    assert report.changed == ("monsters.toml",)
    assert report.added == ("story/my_mod.md",)
    assert report.removed == ("perks.toml",)


def test_a_missing_manifest_counts(tmp_path):
    folder = tmp_path / "data"
    shutil.copytree(integrity.data_folder(), folder)
    (folder / "manifest.json").unlink()
    assert check(folder).unsigned and check(folder).tampered


async def test_hackerman_greets_the_first_modded_run(profile):
    state = generate(1)
    state.modded = True
    game = Game(state, Config(backend="offline"), None, profile=profile)
    result = await game.opening(lambda _: None)
    cards = [e for e in result.events if e.kind == "story"]
    assert cards and cards[0].data["event"] == "hackerman" and "(⌐■_■)" in cards[0].text
    assert "hackerman" in profile.secrets() and "hackerman" in profile.marks()

    again = generate(2)
    again.modded = True
    result = await Game(again, Config(backend="offline"), None, profile=profile).opening(lambda _: None)
    assert not [e for e in result.events if e.kind == "story"]  # once per profile


async def test_honest_runs_stay_quiet(profile):
    result = await Game(generate(1), Config(backend="offline"), None, profile=profile).opening(lambda _: None)
    assert not [e for e in result.events if e.kind == "story"] and "hackerman" not in profile.secrets()


def test_modded_runs_are_marked(profile, monkeypatch):
    monkeypatch.setattr(meta, "shipped_report", lambda: Report(changed=("monsters.toml",)))
    state = meta.start_run(profile, load_content(), "Neo", seed=3)
    assert state.modded and profile.runs(finished=False)[0]["modded"] == 1
    assert "(⌐■_■) modded" in meta.share_card(state)
    assert "🕶️ modded" in meta.share_card(state, emoji=True)


def test_broken_edits_are_explained_and_still_count(monkeypatch, capsys, profile):
    def broken():
        raise ContentError("Problems in the game data files:\n  monsters.toml [monster.goblin]: hp must be ...")
    monkeypatch.setattr(cli, "load_content", broken)
    monkeypatch.setattr(cli, "shipped_report", lambda: Report(changed=("monsters.toml",)))
    assert cli.preflight() is False
    out = capsys.readouterr().out
    assert "Achievement unlocked: Hackerman" in out and "[monster.goblin]: hp must be" in out
    assert "hackerman" in profile.secrets()
    cli.preflight()
    assert "Hackerman, again?" in capsys.readouterr().out


def test_broken_data_without_edits_just_explains(monkeypatch, capsys, profile):
    def broken():
        raise ContentError("Problems in the game data files:\n  art.txt: the file is missing")
    monkeypatch.setattr(cli, "load_content", broken)
    monkeypatch.setattr(cli, "shipped_report", lambda: Report())
    assert cli.preflight() is False
    out = capsys.readouterr().out
    assert "Hackerman" not in out and "art.txt: the file is missing" in out
