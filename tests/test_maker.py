"""`ptg maker`: the maker page served on this computer with a Claude panel (ptg/maker.py). Claude is a stand-in here:
these tests never call the API."""

import base64
import http.client
import io
import json
import re
import shutil
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from ptg import library, maker

PAGE = Path(__file__).resolve().parents[1] / "docs" / "maker" / "index.html"


def rows(*lines: str, size: int = 24) -> list[str]:
    """A frame from the rows given, centred top to bottom in see-through."""
    top = (size - len(lines)) // 2
    return ["." * size] * top + [line.center(size, ".") for line in lines] + ["." * size] * (size - top - len(lines))


BLOB = rows("zzzzzzzz", "zmmmmmmz", "zmtmmtmz", "zmmmmmmz", "zmmmmmmz", "zzzzzzzz")  # a green blob, outlined, 8x6


def art(*frames: list[str], palette=library.ENDESGA) -> dict:
    """Frames in the maker's letters (a-z, A-F for the 32 colours) as the creation JSON's art."""
    size = len(frames[0])
    return {"w": size, "h": size, "palette": list(palette), "frames": [list(f) for f in frames]}


def monster(**extra) -> dict:
    return {"v": 1, "type": "monster", "by": "Lily", "made": "2026-10-27", "art": art(BLOB),
            "fields": {"name": "Moss Blob", "hp": 8, "defense": 12, "attack": 3, "damage": "1d6", "xp": 10, "tier": 1,
                       "tags": ["plant"], "weak": ["fire"], "tell": "puffs up"}, **extra}


def test_each_model_gets_what_it_takes():
    opus = maker.request([{"role": "user", "content": "a toad"}])
    assert opus["model"] == "claude-opus-5-5" and opus["max_tokens"] == maker.MAX_TOKENS
    assert opus["thinking"] == {"type": "adaptive", "display": "updates"} and opus["fallbacks"] == "default"
    assert set(opus["betas"]) == {"thinking-display-updates-2026-08-18", "server-side-fallback-2026-07-01"}
    assert opus["output_config"] == {"effort": "medium"} and opus["cache_control"] == {"type": "ephemeral"}
    assert opus["system"] == [{"type": "text", "text": maker.SYSTEM, "cache_control": {"type": "ephemeral"}}]
    haiku = maker.request([], "claude-haiku-5-5", "low")
    assert haiku["thinking"]["display"] == "summarized" and "fallbacks" not in haiku and "betas" not in haiku
    assert haiku["output_config"] == {"effort": "low"}
    odd = maker.request([], "gpt-5", "frantic")  # anything else is the defaults
    assert odd["model"] == maker.DEFAULT_MODEL and odd["output_config"] == {"effort": maker.DEFAULT_EFFORT}
    assert "temperature" not in opus  # (sampling settings are refused now)


def test_the_prefix_never_changes():
    """The system prompt and the tools are the same bytes on every request: the cache's prefix, and what keeps
    earlier thinking valid."""
    first, second = maker.request([{"role": "user", "content": "a"}]), maker.request([{"role": "user", "content": "b"}])
    assert json.dumps(first["system"]) == json.dumps(second["system"])
    assert json.dumps(first["tools"]) == json.dumps(second["tools"])
    assert "{" not in maker.SYSTEM.replace("{x, y, c}", "")  # (no f-string left unfilled)


def test_claude_is_told_the_games_colours_and_rules():
    for letter, colour in zip(maker.LETTERS, library.ENDESGA):
        assert f"{letter} {colour}" in maker.SYSTEM
    assert maker.OUTLINE == ["z"] and "#181425" in maker.SYSTEM
    for rule in ("24x24", "bob", "drop", "12x12", "windup", "lunge", "death", "half the frame", "splash art"):
        assert rule in maker.SYSTEM, rule


def test_claude_picks_the_floors_a_monster_shows_up_on():
    """Kept to no floors, a monster is on every one its creature type fits, so Claude is told to pick them, and its
    details tool takes them (the page checks them against the game's floors)."""
    details = next(t for t in maker.TOOLS if t["name"] == "details")
    assert "dungeons" in details["input_schema"]["properties"] and "dungeons" in details["description"]
    assert "Pick its floors every time" in maker.SYSTEM and "Norfel" in maker.SYSTEM
    assert re.search(r'const allowed = monster \? \[[^\]]*"dungeons"', PAGE.read_text(encoding="utf-8"))


def test_every_tool_is_one_the_page_runs_and_streams_its_input():
    page = PAGE.read_text(encoding="utf-8")
    tools = re.search(r"const STUDIO_TOOLS = \{(.*?)\n\};", page, re.DOTALL).group(1)
    runs = re.findall(r"^  (?:async )?(\w+)\(", tools, re.MULTILINE)
    for tool in maker.TOOLS:
        assert tool["eager_input_streaming"] is True, tool["name"]
        assert tool["name"] in runs, f"the page has no {tool['name']} tool"
        assert tool["input_schema"]["type"] == "object"
    assert len(runs) == len(maker.TOOLS)  # and runs nothing the server doesn't offer


class Stream:
    """A stand-in for the SDK's message stream: these events, then this message."""

    def __init__(self, events, message):
        self.events, self.message = events, message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        yield from self.events

    def get_final_message(self):
        return self.message


def event(kind: str, **fields):
    return SimpleNamespace(type=kind, **{k: SimpleNamespace(**v) if isinstance(v, dict) else v for k, v in fields.items()})


TURN = [event("content_block_start", content_block={"type": "thinking"}),
        event("content_block_delta", delta={"type": "thinking_delta", "thinking": "Drawing the body first."}),
        event("content_block_delta", delta={"type": "thinking_delta", "thinking": ""}),
        event("content_block_start", content_block={"type": "text"}),
        event("content_block_delta", delta={"type": "text_delta", "text": "A blob coming up."}),
        event("content_block_start", content_block={"type": "tool_use", "name": "draw"}),
        event("content_block_delta", delta={"type": "input_json_delta", "partial_json": "{\"frame\": 1"}),
        event("content_block_start", content_block={"type": "fallback", "to": SimpleNamespace(model="claude-opus-5")})]
MESSAGE = SimpleNamespace(model_dump=lambda **_: {
    "model": "claude-opus-5-5", "stop_reason": "tool_use",
    "content": [{"type": "thinking", "thinking": "Drawing the body first.", "signature": "sig"},
                {"type": "text", "text": "A blob coming up."},
                {"type": "tool_use", "id": "toolu_1", "name": "draw", "input": {"frame": 1, "rows": BLOB}}],
    "usage": {"input_tokens": 20, "output_tokens": 300, "cache_read_input_tokens": 4000,
              "cache_creation_input_tokens": None}})


def test_a_turn_reaches_the_page_as_it_comes_then_whole():
    sent = []
    maker.relay(Stream(TURN, MESSAGE), sent.append)
    assert [e["type"] for e in sent] == ["note", "text", "tool", "fallback", "message"]
    assert sent[0]["text"] == "Drawing the body first." and sent[2]["name"] == "draw"
    assert sent[3]["model"] == "claude-opus-5"
    whole = sent[-1]
    assert whole["stop_reason"] == "tool_use" and whole["content"][0]["signature"] == "sig"  # kept for next time
    assert whole["usage"] == {"input_tokens": 20, "output_tokens": 300, "cache_read_input_tokens": 4000,
                              "cache_creation_input_tokens": 0}


def test_the_games_checks_on_a_creation():
    good = maker.check(monster())
    assert good["ok"] and good["said"][0].startswith("Added monster Moss Blob (moss_blob) by Lily")
    small = ("It fills 10% of its frame; the game's art fills at least half (its monsters 54-100%). "
             "Draw it bigger.")  # (8 by 7 pixels, its bob included: outlined, and nothing else to say)
    assert good["art"] == [small]
    unnamed = maker.check(monster(fields={"name": ""}))
    assert not unnamed["ok"] and "name" in unnamed["said"][0]
    plain = monster(art=art(rows(*["mmmmmmmmmmmmmmmm"] * 16)))  # big, but no outline
    assert any("aren't outline" in note for note in maker.check(plain)["art"])


def test_a_drawing_that_loses_its_feet_or_grows_a_second_ring_is_named():
    big = rows("zzzzzzzzzzzzzzzzzzzzzzzz", *["zmmmmmmmmmmmmmmmmmmmmmmz"] * 22, "zzzzzzzzzzzzzzzzzzzzzzzz")
    slid = ["." * 24] + big[:-1]  # frame 1 slid down whole, though it uses its bottom row
    assert any("falls off" in note for note in maker.art_notes(monster(art=art(big, slid))))
    ringed = rows(".........zzzzzz.........", "........z......z........", *BLOB[9:15], "........z......z........",
                  ".........zzzzzz.........")
    assert any("second ring" in note for note in maker.art_notes(monster(art=art(BLOB, ringed))))


def test_a_four_frame_animation_goes_in_whole():
    """Up to four frames, as the game plays and the importer keeps them, as long as there's no gap."""
    lit = [line.replace("t", "l") for line in BLOB]  # eyes lit in amber...
    wide = rows("zzzzzzzzzz", "zmmmmmmmmz", "zmtmmmmtmz", "zmmmmmmmmz", "zzzzzzzzzz")  # ...a stretch, a squash
    four = monster(art=art(BLOB, lit, wide, lit))
    checked = maker.check(four)
    assert checked["ok"] and [note[:9] for note in checked["art"]] == ["It fills "]  # (only that it's small)
    assert "with 4 frames" not in checked["said"][0]  # (the importer's word: no complaint about them)
    sheet = Image.open(io.BytesIO(base64.b64decode(maker.preview(four)["image"])))
    assert sheet.size == (56 + 104 * 6, 104 * 7)  # (its idle row: four frames)
    gap = maker.art_notes(monster(art=art(BLOB, ["." * 24] * 24, wide, lit)))
    assert any("leave out frames 3 to 4" in note for note in gap)  # (the importer bobs frame 1 and drops the rest)
    blank_end = maker.art_notes(monster(art=art(BLOB, lit, ["." * 24] * 24)))
    assert any("Frame 3 is empty" in note for note in blank_end)


def test_an_items_small_version_has_as_many_frames_as_its_drawing():
    drawing = rows(*["zmmmmmmmmmmmmmmz"] * 16)
    item = {"type": "item", "by": "Lily", "fields": {"name": "Moss Gem", "kind": "trinket", "tier": 1},
            "art": art(drawing, drawing[1:] + ["." * 24], drawing), "small": art(rows(*["zmmmmmmmmz"] * 10, size=12))}
    assert any("has 2 frames and the drawing 3" in note for note in maker.art_notes(item))


def test_an_item_is_told_about_its_small_version():
    item = {"type": "item", "by": "Lily", "fields": {"name": "Moss Gem", "kind": "trinket", "tier": 1},
            "art": art(rows(*["zmmmmmmmmmmmmmmz"] * 16))}
    assert any("No small version" in note for note in maker.art_notes(item))
    item["small"] = art(rows("zz", size=12))  # tiny, in a colour the drawing has
    notes = maker.art_notes(item)
    assert any("under three quarters" in note for note in notes)
    item["small"] = art(rows(*["kkkkkkkkkk"] * 10, size=12))  # big enough, in amber the drawing doesn't use
    assert any("#feae34" in note for note in maker.art_notes(item))


def test_seeing_it_in_a_fight():
    out = maker.preview(monster())
    assert out["ok"] and out["said"].startswith("Frame 2 is empty")
    sheet = Image.open(io.BytesIO(base64.b64decode(out["image"])))
    assert sheet.size == (56 + 104 * 6, 104 * 7)  # idle, windup, dizzy, lunge, shake, hit, death (6 steps)
    item = {"type": "item", "fields": {"name": "Gem"}, "art": art(BLOB, BLOB)}
    assert Image.open(io.BytesIO(base64.b64decode(maker.preview(item)["image"]))).height == 104 * 8  # and small
    assert not maker.preview({"type": "monster"})["ok"]


class Claude:
    """A stand-in client: every turn streams TURN and ends with MESSAGE, and remembers what it was asked."""

    def __init__(self, fail=None):
        self.asked, self.fail = [], fail
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self.stream))

    def stream(self, **params):
        self.asked.append(params)
        if self.fail:
            raise self.fail
        return Stream(TURN, MESSAGE)


@pytest.fixture
def served(tmp_path):
    """ptg maker on a free port, with a stand-in Claude and a copy of the game's data for "Add to the game"."""
    data = tmp_path / "data"
    shutil.copytree(library.data_folder(), data)
    studio = maker.Studio(client=Claude(), folder=data)
    server = maker.make_server(0, library.maker_folder(), studio)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, studio, data
    server.shutdown()
    server.server_close()


def call(server, method, path, body=None, token=None, host=None):
    conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Maker-Token"] = token
    if host:
        headers["Host"] = host
    conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
    response = conn.getresponse()
    return response.status, response.read().decode()


def test_the_page_and_its_panel_are_served_only_to_this_computer(served):
    server, studio, _ = served
    status, page = call(server, "GET", "/")
    assert status == 200 and "Monster <span>&amp;</span> Item Maker" in page and 'id="studio"' in page
    status, body = call(server, "GET", "/studio.json")
    info = json.loads(body)
    assert info["enabled"] and info["token"] == studio.token and info["model"] == "claude-opus-5-5"
    assert call(server, "GET", "/studio.json", host="evil.example")[0] == 403  # (a rebound name)
    assert call(server, "POST", "/api/claude", {"messages": [{"role": "user", "content": "hi"}]})[0] == 403
    assert call(server, "POST", "/api/claude", {"messages": []}, token="guess")[0] == 403


def test_a_turn_streams_to_the_page(served):
    pytest.importorskip("anthropic")  # (the claude extra: its errors are what a turn tells apart)
    server, studio, _ = served
    messages = [{"role": "user", "content": [{"type": "text", "text": "a blob"}]}]
    status, body = call(server, "POST", "/api/claude", {"messages": messages, "effort": "high"}, token=studio.token)
    events = [json.loads(line[6:]) for line in body.split("\n\n") if line.startswith("data: ")]
    assert status == 200 and [e["type"] for e in events] == ["note", "text", "tool", "fallback", "message"]
    asked = studio.client.asked[-1]
    assert asked["messages"] == messages and asked["output_config"] == {"effort": "high"}
    assert all(tool["eager_input_streaming"] for tool in asked["tools"])


def test_a_garbled_tool_input_asks_the_page_to_try_again(served):
    pytest.importorskip("anthropic")
    server, studio, _ = served
    studio.client = Claude(fail=ValueError("unparseable tool input"))
    _, body = call(server, "POST", "/api/claude", {"messages": [{"role": "user", "content": "hi"}]}, token=studio.token)
    assert json.loads(body.split("\n\n")[0][6:]) == {"type": "retry"}


def test_checks_previews_and_adding_to_the_game(served):
    server, studio, data = served
    status, body = call(server, "POST", "/api/check", {"creation": monster()}, token=studio.token)
    assert status == 200 and json.loads(body)["ok"]
    assert json.loads(call(server, "POST", "/api/preview", {"creation": monster()}, token=studio.token)[1])["ok"]
    nameless = monster(by="")
    assert not json.loads(call(server, "POST", "/api/add", {"creation": nameless}, token=studio.token)[1])["ok"]
    real = (library.data_folder() / "monsters.toml").read_text(encoding="utf-8")
    kept = monster()
    kept["fields"]["dungeons"] = ["overgrown_ruins"]
    added = json.loads(call(server, "POST", "/api/add", {"creation": kept}, token=studio.token)[1])
    assert added["ok"] and added["said"][0] == "Added monster Moss Blob (moss_blob) by Lily, lives in The Overgrown Ruins."
    assert "[monster.moss_blob]" in (data / "monsters.toml").read_text(encoding="utf-8")
    assert (data / "sprites" / "moss_blob.png").is_file()
    assert (library.data_folder() / "monsters.toml").read_text(encoding="utf-8") == real  # the game's own: untouched
    assert call(server, "POST", "/api/check", {"nothing": 1}, token=studio.token)[0] == 400


def test_without_a_key_the_panel_says_how_to_get_one(monkeypatch):
    pytest.importorskip("anthropic")
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(maker.Path, "home", lambda: Path("/nonexistent-home"))
    studio = maker.Studio()
    assert "ANTHROPIC_API_KEY" in studio.problem
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert maker.Studio().problem == ""
