"""`ptg serve` (ptg/serve.py): one link, a page that asks who's playing, and each name its own saves."""

import asyncio
import json
import re

from aiohttp import WSMsgType
from aiohttp.test_utils import TestClient, TestServer

from ptg import config, serve


def test_a_name_is_its_folder_however_it_is_typed(tmp_path):
    assert serve.player_slug("Ava Rose") == serve.player_slug("  ava   ROSE ") == "ava-rose"
    assert serve.player_slug("Émile!") == "emile" and serve.player_slug("!!!") == ""
    home = serve.player_folder(tmp_path, "Ava Rose")
    assert home == tmp_path / "ava-rose" and json.loads((home / "config.json").read_text())["player_name"] == "Ava Rose"
    serve.player_folder(tmp_path, "AVA ROSE")  # the same player: their settings stay as they were
    assert json.loads((home / "config.json").read_text())["player_name"] == "Ava Rose"


def test_the_narrator_is_claude_only_with_a_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert serve.command().endswith("-m ptg --continue --offline")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    assert serve.command().endswith(f"--backend anthropic --model {serve.DEFAULT_MODEL}")
    monkeypatch.setenv("PTG_MODEL", "claude-sonnet-5-5")
    assert serve.command().endswith("--model claude-sonnet-5-5")


async def test_one_link_asks_who_is_playing_and_each_name_gets_its_own_game(tmp_path):
    server = serve.make_server(tmp_path, "localhost", 8000, "http://localhost:8000")
    async with TestClient(TestServer(await server._make_app())) as client:
        page = await (await client.get("/")).text()
        assert "Who's playing?" in page and 'type="password"' not in page
        moved = await client.get("/play?name=Ava", allow_redirects=False)
        assert moved.status == 303 and moved.headers["Location"] == "/play/ava" and (tmp_path / "ava").is_dir()
        game = await (await client.get("/play/ava")).text()
        assert "ws://localhost:8000/play/ava/ws" in game  # textual-serve's page, wired to Ava's game
        assert (await client.get("/play/nobody", allow_redirects=False)).headers["Location"] == "/"
        assert "with a letter or a number" in await (await client.get("/play?name=!!!")).text()


async def test_a_password_once_a_browser(tmp_path):
    server = serve.make_server(tmp_path, "localhost", 8000, "http://localhost:8000", password="dragon")
    async with TestClient(TestServer(await server._make_app())) as client:
        assert 'type="password"' in await (await client.get("/")).text()
        assert "not the password" in await (await client.get("/play?name=Ava&password=wyrm")).text()
        assert not (tmp_path / "ava").exists()
        assert (await client.get("/play/ava", allow_redirects=False)).status == 303
        let_in = await client.get("/play?name=Ava&password=dragon", allow_redirects=False)
        assert let_in.status == 303 and "dragon" not in let_in.headers["Set-Cookie"]
        assert (await client.get("/play/ava")).status == 200  # the browser remembers
        assert 'type="password"' not in await (await client.get("/")).text()


async def test_the_dungeon_can_be_full(tmp_path):
    server = serve.make_server(tmp_path, "localhost", 8000, "http://localhost:8000", max_games=0)
    async with TestClient(TestServer(await server._make_app())) as client:
        assert "The dungeon is full" in await (await client.get("/play?name=Ava")).text()


async def test_a_name_plays_its_own_game_and_a_second_tab_ends_the_first(tmp_path):
    server = serve.make_server(tmp_path, "localhost", 8000, "http://localhost:8000")
    async with TestClient(TestServer(await server._make_app())) as client:
        await client.get("/play?name=Ava", allow_redirects=False)
        first = await client.ws_connect("/play/ava/ws?width=120&height=40")
        message = await first.receive(timeout=30)  # the game, drawing its first screen
        assert message.type == WSMsgType.BINARY and (tmp_path / "ava" / "profile.db").exists()
        second = await client.ws_connect("/play/ava/ws?width=120&height=40")
        while (await first.receive(timeout=30)).type not in (WSMsgType.CLOSE, WSMsgType.CLOSED):
            pass  # the first tab's game ends...
        assert (await second.receive(timeout=30)).type == WSMsgType.BINARY  # ...and the second one's draws
        assert list(server.playing) == ["ava"]
        await second.close()
        for _ in range(100):
            if not server.playing:
                break
            await asyncio.sleep(0.1)
        assert not server.playing


def test_a_test_room_runs_instead_of_the_players_run(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert serve.command(("lenny", "items=pickle+pickle", 2)).endswith(
        "-m ptg --test-room lenny --loadout items=pickle+pickle --floor 2 --offline")


async def test_test_rooms_only_with_the_switch_on(tmp_path):
    server = serve.make_server(tmp_path, "localhost", 8000, "http://localhost:8000")
    async with TestClient(TestServer(await server._make_app())) as client:
        assert "Test rooms" not in await (await client.get("/")).text()
        assert (await client.get("/test")).status == 404


async def test_the_test_rooms_page_sends_you_next_door_to_whoever_you_pick(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    server = serve.make_server(tmp_path, "localhost", 8000, "http://localhost:8000", password="dragon",
                               test_rooms=True)
    async with TestClient(TestServer(await server._make_app())) as client:
        assert '<a href="/test">Test rooms</a>' in await (await client.get("/")).text()
        page = await (await client.get("/test")).text()
        assert 'value="swoogy"' in page and 'value="shiny_shop"' in page and 'type="password"' in page
        assert "not the password" in await (await client.get("/test/play?name=Ava&password=wyrm&who=lenny")).text()
        assert "no test room" in await (await client.get("/test/play?name=Ava&password=dragon&who=nobody")).text()
        assert "a kit is" in await (await client.get("/test/play?name=Ava&password=dragon&who=lenny&own=x")).text()
        moved = await client.get("/test/play?name=Ava&password=dragon&who=lenny&floor=2&kit=random&own=items%3D"
                                 "pickle%2Bpickle", allow_redirects=False)
        assert moved.status == 303 and moved.headers["Location"] == "/test/ava/lenny/2/items=pickle%2Bpickle"
        game = await (await client.get(moved.headers["Location"])).text()
        assert "ws://localhost:8000/test/ava/lenny/2/items=pickle+pickle/ws" in game  # (a + in a path is a +)
        assert (await client.get("/test/ava/nobody/1/new", allow_redirects=False)).headers["Location"] == "/test"
        assert (await client.get("/test/ava/nobody/1/new/ws")).status == 403
        socket = await client.ws_connect("/test/ava/lenny/2/items=pickle+pickle/ws?width=120&height=40")
        assert (await socket.receive(timeout=30)).type == WSMsgType.BINARY  # the test room, drawing
        assert server.playing["ava"].command.split()[-7:] == ["--test-room", "lenny", "--loadout",
                                                             "items=pickle+pickle", "--floor", "2", "--offline"]
        await socket.close()


async def test_the_game_page_is_made_for_phones(tmp_path):
    server = serve.make_server(tmp_path, "localhost", 8000, "http://localhost:8000", test_rooms=True)
    async with TestClient(TestServer(await server._make_app())) as client:
        await client.get("/play?name=Ava", allow_redirects=False)
        game = await (await client.get("/play/ava")).text()  # ptg's page (web/app_index.html), not textual-serve's
        assert ('<meta name="viewport" content="width=device-width, initial-scale=1, '
                'interactive-widget=resizes-content"') in game
        assert "touch-action: manipulation" in game and "visualViewport" in game and '"wheel"' in game
        assert 'data-session-websocket-url="ws://localhost:8000/play/ava/ws"' in game
        assert 'data-touch-websocket-url="ws://localhost:8000/play/ava/ws/touch"' in game  # for a finger
        assert "(pointer: coarse)" in game and 'setAttribute("inputmode", "none")' in game and 'id="keyboard"' in game
        assert 'data-font-size=""' in game and "across / 40 / 0.6" in game  # the page picks it from its width...
        # ...and by touch from the screen's short side too, so a phone loaded sideways still fits 40 upright...
        assert "touch ? Math.min(innerWidth, screen.width, screen.height) : innerWidth" in game
        assert 'data-font-size="12"' in await (await client.get("/play/ava?fontsize=12")).text()  # ...unless asked
        assert "fonts.googleapis" not in game  # (the font is textual-serve's own copy, from this server)
        for path in ("/static/js/textual.js", "/static/css/xterm.css", "/static/fonts/RobotoMono-VariableFont_wght.ttf",
                     "/static/fonts/RobotoMono-Italic-VariableFont_wght.ttf"):
            assert (await client.get(path)).status == 200, path
        room = await (await client.get("/test/ava/lenny/2/random")).text()
        assert 'data-touch-websocket-url="ws://localhost:8000/test/ava/lenny/2/random/ws/touch"' in room


async def test_a_game_played_by_touch_is_told_so(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)  # (the games are narrated offline)
    monkeypatch.setenv("PTG_TOUCH", "1")  # (the server's own setting never reaches a game played with a mouse)
    server = serve.make_server(tmp_path, "localhost", 8000, "http://localhost:8000", test_rooms=True)
    async with TestClient(TestServer(await server._make_app())) as client:
        await client.get("/play?name=Ava", allow_redirects=False)
        for path, touch in (("/play/ava/ws/touch", "1"), ("/play/ava/ws", "0"),
                            ("/test/ava/lenny/2/random/ws/touch", "1")):
            socket = await client.ws_connect(f"{path}?width=40&height=34")
            assert (await socket.receive(timeout=30)).type == WSMsgType.BINARY, path  # the game, drawing
            assert server.playing["ava"]._build_environment(40, 34)["PTG_TOUCH"] == touch, path
            await socket.close()


def test_touch_mode_follows_the_page(monkeypatch):
    monkeypatch.delenv("PTG_TOUCH", raising=False)
    assert not config.touch()
    monkeypatch.setenv("PTG_TOUCH", "0")
    assert not config.touch()
    monkeypatch.setenv("PTG_TOUCH", "1")
    assert config.touch()


async def test_a_served_games_sound_plays_in_its_players_browser(tmp_path, monkeypatch):
    """The game's sound goes to the page (PTG_SOUND=web), not the server's speakers: its title music, as a message on
    the game's websocket for the page to play. The game's other messages still go to textual-serve as before."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)  # (the game is narrated offline)
    server = serve.make_server(tmp_path, "localhost", 8000, "http://localhost:8000")
    async with TestClient(TestServer(await server._make_app())) as client:
        await client.get("/play?name=Ava", allow_redirects=False)
        socket = await client.ws_connect("/play/ava/ws?width=120&height=40")
        message = await socket.receive(timeout=30)
        while message.type == WSMsgType.BINARY:  # (the game, drawing its title screen)
            message = await socket.receive(timeout=30)
        assert json.loads(message.data) == ["ptg_sound", {"type": "ptg_sound", "do": "loop", "file": "title_music.wav",
                                                          "gain": 0.42, "fade_in": 0.0, "fade_out": 0.8}]
        game = server.playing["ava"]
        assert game._build_environment()["PTG_SOUND"] == "web"
        await game.on_meta(json.dumps({"type": "open_url", "url": "https://example.com", "new_tab": True}).encode())
        message = await socket.receive(timeout=30)
        while message.type == WSMsgType.BINARY or "ptg_sound" in message.data:
            message = await socket.receive(timeout=30)
        assert json.loads(message.data) == ["open_url", {"url": "https://example.com", "new_tab": True}]
        await socket.close()


async def test_the_page_loads_the_sounds_once_and_keeps_them(tmp_path):
    """The game's page knows where the sounds are, and which to load ahead (all but the music, loaded when it's
    asked for). A sound's address has a stamp of them all in it, so the browser keeps it for good."""
    server = serve.make_server(tmp_path, "localhost", 8000, "http://localhost:8000")
    stamp, files = serve.sound_files()
    async with TestClient(TestServer(await server._make_app())) as client:
        await client.get("/play?name=Ava", allow_redirects=False)
        game = await (await client.get("/play/ava")).text()
        assert f'data-sounds-url="/sounds/{stamp}/"' in game and "new AudioContext" in game
        ahead = re.search(r'data-sounds="([^"]*)"', game).group(1).split()
        assert "coin.wav" in ahead and "thunder_3.wav" in ahead and not any("_music" in name for name in ahead)
        assert len(ahead) + 5 == len(files)  # (the five music tracks)
        reply = await client.get(f"/sounds/{stamp}/coin.wav")
        assert reply.status == 200 and await reply.read() == files["coin.wav"].read_bytes()
        assert reply.headers["Cache-Control"] == "public, max-age=31536000, immutable"
        for wrong in (f"/sounds/{stamp}/nothing.wav", "/sounds/0123456789ab/coin.wav", f"/sounds/{stamp}/..%2Fserve.py"):
            assert (await client.get(wrong)).status == 404, wrong
