"""Command line entry point: `ptg` (or `python -m ptg`)."""

from __future__ import annotations

import argparse
import asyncio
import random
import sys

from .config import DEFAULT_URLS, Config, load_config, load_game
from .game import Game
from .llm import LLMError, make_llm
from .llm.narrator import intro
from .world import generate, render_map


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="ptg", description="A seeded dungeon crawl narrated by a language model.")
    parser.add_argument("--seed", type=int, help="dungeon seed (same seed, same dungeon)")
    parser.add_argument("--continue", dest="resume", action="store_true", help="resume the autosave")
    parser.add_argument("--setup", action="store_true", help="open the settings screen first")
    parser.add_argument("--plain", action="store_true", help="plain text mode, no full-screen UI")
    parser.add_argument("--offline", action="store_true", help="play without a language model")
    parser.add_argument("--backend", choices=["openai", "anthropic", "offline"], help="override the narrator backend")
    parser.add_argument("--url", help="OpenAI-compatible server URL, e.g. http://localhost:1234/v1")
    parser.add_argument("--model", help="model name (default: whatever the server has loaded)")
    parser.add_argument("--name", help="your character's name")
    return parser.parse_args(argv)


def build_config(args: argparse.Namespace) -> Config | None:
    config = load_config()
    overrides = {k: v for k, v in {"backend": "offline" if args.offline else args.backend, "url": args.url,
                                   "model": args.model, "player_name": args.name}.items() if v}
    if args.url and not args.backend and not args.offline:
        overrides["backend"] = "openai"
    if config is None:
        return Config(**overrides) if overrides else None
    return config.model_copy(update=overrides)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    config = build_config(args)
    if args.plain:
        try:
            asyncio.run(play_plain(config or Config(url=DEFAULT_URLS["lmstudio"]), args.seed, args.resume))
        except (KeyboardInterrupt, EOFError):
            print("\nGame saved. Bye.")
        return
    from .ui.app import PTGApp

    PTGApp(config, seed=args.seed, setup=args.setup, resume=args.resume).run()


async def play_plain(config: Config, seed: int | None, resume: bool) -> None:
    llm = make_llm(config)
    if llm is not None:
        try:
            await llm.prepare()
            print(f"[narrator: {llm.name}]")
        except LLMError as e:
            print(f"[no narrator: {e}. Playing offline.]")
            llm = None
    state = load_game() if resume else None
    fresh = state is None
    if fresh:
        state = generate(seed if seed is not None else random.randrange(1_000_000), config.player_name)
    game = Game(state, config, llm)
    print(f"\n=== {game.theme.name} (seed {state.seed}) ===\n")

    def write(chunk: str) -> None:
        sys.stdout.write(chunk)
        sys.stdout.flush()

    def show_rolls(events) -> None:
        for event in events:
            if event.roll:
                print(f"  [{event.roll}]")

    if fresh:
        await intro(llm, state.player.name, game.theme.name, write)
        print("\n")
        await game.opening(write)
    else:
        print(state.log[-1].text if state.log else "")
    try:
        while not state.over:
            p = state.player
            print(f"\n\nHP {p.hp}/{p.max_hp} · Level {p.level} · Gold {p.gold}")
            for i, action in enumerate(game.actions, 1):
                print(f"  {i}. {action.label}")
            raw = input("> ").strip()
            if raw in ("quit", "exit"):
                print("Game saved.")
                return
            if raw == "map":
                print("\n".join(render_map(state)))
                continue
            if not raw:
                continue
            result = await game.act(raw, write, show_rolls)
            for error in result.errors:
                print(f"\n  ({error})")
        print("\n\n*** VICTORY! ***" if state.status == "won" else "\n\n*** YOU DIED ***")
    finally:
        await game.aclose()
