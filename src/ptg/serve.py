"""`ptg serve`: the game in a web browser, for a few players sharing one link, each with their own saves.

Built on textual-serve, which runs one game for each browser tab. The link opens a page that asks who's playing, and
the name typed there is that player's own folder under the data directory (PTG_DATA): their profile, souls, settings
and autosave. The same name later picks up where they left off, straight back into their run. A second tab with the
same name ends the first, so a run is only ever played in one place. Set PTG_PASSWORD and the page asks for it too
(once a browser: it's remembered). PTG_MAX_GAMES caps the games running at once: 5, at about 80 MB each, fits the
512 MB of Render's Starter plan.

The narrator is Claude when ANTHROPIC_API_KEY is set (PTG_MODEL picks the model, Haiku by default) and offline
otherwise. Every game runs hosted (PTG_HOSTED=1, see config.hosted) and quiet: its sound would play on the server.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import html
import logging
import os
import re
import shlex
import sys
import unicodedata
from pathlib import Path

from .config import Config

DEFAULT_MODEL = "claude-haiku-5-5"  # a few cents a run (docs/plans/cross-platform-and-mobile.md)
MAX_NAME = 24
PASS_COOKIE = "ptg_pass"

log = logging.getLogger("textual-serve")


def player_slug(name: str) -> str:
    """A name as its folder, the same however it's typed: "Ava Rose" and "ava rose" are both ava-rose, Émile emile."""
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")


def player_folder(data: Path, name: str) -> Path:
    """A player's own PTG_HOME, made the first time they play, with their name in its settings."""
    home = data / player_slug(name)
    if not (home / "config.json").exists():
        home.mkdir(parents=True, exist_ok=True)
        (home / "config.json").write_text(Config(player_name=name).model_dump_json(indent=2), encoding="utf-8")
    return home


def command() -> str:
    """What a player's tab runs: their game, back into their run if one is going, with the server's narrator."""
    args = [sys.executable, "-m", "ptg", "--continue"]
    if os.environ.get("ANTHROPIC_API_KEY"):
        args += ["--backend", "anthropic", "--model", os.environ.get("PTG_MODEL") or DEFAULT_MODEL]
    else:
        args.append("--offline")
    return shlex.join(args)


def pass_token(password: str) -> str:
    """What the browser keeps once the password was right (the password itself never sits in a cookie)."""
    return hashlib.sha256(f"ptg:{password}".encode()).hexdigest()


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Procedural Terminal Game</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; background: #0b0b14; color: #e8e8f4;
          font: 16px/1.5 Menlo, Monaco, "Courier New", monospace; }}
  form {{ width: min(26rem, calc(100vw - 2rem)); padding: 1.5rem; border: 3px double #7b8cff; background: #12121f; }}
  h1 {{ margin: 0 0 .25rem; font-size: 1.1rem; color: #7b8cff; letter-spacing: .05em; }}
  p {{ margin: 0 0 1rem; color: #9a9cc0; }}
  label {{ display: block; margin: .75rem 0 .25rem; color: #ffb000; }}
  input {{ box-sizing: border-box; width: 100%; padding: .5rem; border: 1px solid #3a3a5c; background: #0b0b14;
           color: #e8e8f4; font: inherit; }}
  button {{ margin-top: 1.25rem; width: 100%; padding: .6rem; border: 0; background: #7b8cff; color: #0b0b14;
            font: inherit; font-weight: bold; cursor: pointer; }}
  .error {{ color: #ff4b4b; }}
</style>
</head>
<body>
<form method="get" action="/play">
  <h1>PROCEDURAL TERMINAL GAME</h1>
  <p>A dungeon that listens. Type anything.</p>
  {error}
  <label for="name">Who's playing?</label>
  <input id="name" name="name" maxlength="{max_name}" value="{name}" autocomplete="nickname" required autofocus>
  {password}
  <button type="submit">Play</button>
  <p style="margin-top:1rem">Same name, same saves: you pick up where you left off.</p>
</form>
<script>
  const field = document.getElementById("name");
  try {{ if (!field.value) field.value = localStorage.getItem("ptg-name") || ""; }} catch (e) {{}}
  document.querySelector("form").addEventListener("submit", () => {{
    try {{ localStorage.setItem("ptg-name", field.value.trim()); }} catch (e) {{}}
  }});
</script>
</body>
</html>
"""


def name_page(name: str = "", error: str = "", ask_password: bool = False) -> str:
    """The page that asks who's playing (and, with PTG_PASSWORD set, the password, until this browser knows it)."""
    password = ('<label for="password">Password</label>'
                '<input id="password" name="password" type="password" required>') if ask_password else ""
    return PAGE.format(name=html.escape(name), max_name=MAX_NAME, password=password,
                       error=f'<p class="error">{html.escape(error)}</p>' if error else "")


def make_server(data: Path, host: str, port: int, public_url: str, password: str = "", max_games: int = 5):
    """textual-serve's server, behind a page that asks who's playing, with a folder for each player. (Built here,
    not at import: textual-serve is the `web` extra.)"""
    import aiohttp_jinja2
    import jinja2
    from aiohttp import web
    from textual_serve.app_service import AppService
    from textual_serve.server import Server, to_int

    token = pass_token(password) if password else ""

    class PlayerService(AppService):
        """One player's game, in their own folder."""

        def __init__(self, command: str, home: Path, **kwargs) -> None:
            super().__init__(command, **kwargs)
            self.home = home

        def _build_environment(self, width: int = 80, height: int = 24) -> dict[str, str]:
            environment = super()._build_environment(width, height)
            environment.update(PTG_HOME=str(self.home), PTG_HOSTED="1", PTG_SOUND="0")
            return environment

        async def stop(self) -> None:
            await super().stop()
            if self._process is not None:  # (textual-serve leaves the game's input open: close it, and see it out)
                self._process.stdin.close()
                await self._process.wait()

    class PlayersServer(Server):
        def __init__(self) -> None:
            super().__init__("ptg", host=host, port=port, title="Procedural Terminal Game", public_url=public_url)
            self.playing: dict[str, PlayerService] = {}  # each player's open game, by their folder's name

        async def _make_app(self) -> web.Application:
            app = web.Application()
            aiohttp_jinja2.setup(app, loader=jinja2.FileSystemLoader(self.templates_path))
            app.add_routes([
                web.get("/", self.handle_name, name="name"),
                web.get("/play", self.handle_play, name="play"),
                web.get("/play/{player}", self.handle_index, name="index"),
                web.get("/play/{player}/ws", self.handle_websocket, name="websocket"),
                web.get("/download/{key}", self.handle_download, name="download"),
                web.static("/static", self.statics_path, name="static"),
            ])
            app.on_startup.append(self.on_startup)
            app.on_shutdown.append(self.on_shutdown)
            return app

        async def on_startup(self, app: web.Application) -> None:
            self.console.print(f"Procedural Terminal Game on {self.public_url}"
                               f"{' (with a password)' if password else ''}, up to {max_games} games at once")

        def let_in(self, request: web.Request) -> bool:
            return not token or hmac.compare_digest(request.cookies.get(PASS_COOKIE, ""), token)

        def full(self, player: str) -> bool:
            return player not in self.playing and len(self.playing) >= max_games

        async def handle_name(self, request: web.Request) -> web.Response:
            return web.Response(text=name_page(ask_password=not self.let_in(request)), content_type="text/html")

        async def handle_play(self, request: web.Request) -> web.StreamResponse:
            """The name page's answer: their folder (made the first time), then their game."""
            name = " ".join(request.query.get("name", "").split())[:MAX_NAME]
            given = request.query.get("password", "")
            knows = self.let_in(request) or bool(given) and hmac.compare_digest(pass_token(given), token)

            def again(error: str) -> web.Response:
                return web.Response(text=name_page(name, error, ask_password=not knows), content_type="text/html")

            if not knows:
                return again("That's not the password." if given else "")
            if not player_slug(name):
                return again("Type a name with a letter or a number in it.")
            if self.full(player_slug(name)):
                return again(f"The dungeon is full right now ({max_games} playing). Try again in a bit.")
            player_folder(data, name)
            onward = web.HTTPSeeOther(f"/play/{player_slug(name)}")
            if token and not self.let_in(request):
                onward.set_cookie(PASS_COOKIE, token, max_age=365 * 24 * 3600, httponly=True, samesite="Lax",
                                  secure=self.public_url.startswith("https"))
            raise onward

        def known(self, request: web.Request) -> str | None:
            """The player a game page or its websocket is for, if they may play and have been through the name
            page (which made their folder); otherwise None."""
            player = request.match_info["player"]
            if not self.let_in(request) or player != player_slug(player) or not (data / player).is_dir():
                return None
            return player

        async def handle_index(self, request: web.Request) -> web.Response:
            """A player's game page: textual-serve's, its websocket the one for their folder."""
            player = self.known(request)
            if player is None:
                raise web.HTTPSeeOther("/")
            url = f"{self.public_url}{request.app.router['websocket'].url_for(player=player)}"
            scheme = "wss:" if self.public_url.startswith("https") else "ws:"
            return aiohttp_jinja2.render_template("app_index.html", request, {
                "font_size": to_int(request.query.get("fontsize", "16"), 16),
                "app_websocket_url": scheme + url.split(":", 1)[1],
                "config": {"static": {"url": f"{self.public_url}/static/"}},
                "application": {"name": self.title},
            })

        async def handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
            """A player's game, for as long as their tab is open (textual-serve's, in their folder)."""
            player = self.known(request)
            if player is None or self.full(player):
                raise web.HTTPForbidden()
            websocket = web.WebSocketResponse(heartbeat=15)
            width = to_int(request.query.get("width", "80"), 80)
            height = to_int(request.query.get("height", "24"), 24)
            service: PlayerService | None = None
            try:
                await websocket.prepare(request)
                older = self.playing.pop(player, None)
                if older is not None:  # the same player in a second tab: the first one ends, its game saved
                    await older.stop()
                service = PlayerService(command(), data / player, write_bytes=websocket.send_bytes,
                                        write_str=websocket.send_str, close=websocket.close,
                                        download_manager=self.download_manager, debug=self.debug)
                self.playing[player] = service
                await service.start(width, height)
                await self._process_messages(websocket, service)
            except asyncio.CancelledError:
                await websocket.close()
            except Exception as error:
                log.exception(error)
            finally:
                if service is not None:
                    await service.stop()
                    if self.playing.get(player) is service:
                        del self.playing[player]
            return websocket

    return PlayersServer()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="ptg serve", description="Serve the game to web browsers: one link, each "
                                                                  "player under their own name (see ptg/serve.py).")
    parser.add_argument("--host", default="localhost", help="where to listen (0.0.0.0 for everywhere)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    parser.add_argument("--public-url", help="the address players use (default: PTG_PUBLIC_URL, RENDER_EXTERNAL_URL "
                                             "on Render, or http://HOST:PORT)")
    parser.add_argument("--data", default=os.environ.get("PTG_DATA", "players"), help="where players' saves go")
    args = parser.parse_args(argv)
    try:
        import textual_serve  # noqa: F401
    except ImportError:
        print("ptg serve needs textual-serve: uv sync --extra web (or pip install 'ptg[web]').")
        return 1
    public_url = (args.public_url or os.environ.get("PTG_PUBLIC_URL") or os.environ.get("RENDER_EXTERNAL_URL")
                  or f"http://{args.host}:{args.port}").rstrip("/")
    make_server(Path(args.data), args.host, args.port, public_url, password=os.environ.get("PTG_PASSWORD", ""),
                max_games=int(os.environ.get("PTG_MAX_GAMES", "5"))).serve()
    return 0
