"""Command line entry point: `ptg` (or `python -m ptg`)."""

from __future__ import annotations

import argparse
import asyncio
import sys
import textwrap

from .config import DEFAULT_URLS, Config, load_config, load_game
from .content import load_content
from .game import Game
from .layout import plain_lines
from .llm import LLMError, make_llm
from .llm.narrator import intro
from .meta import share_card, start_run
from .profile import Profile
from .world import render_map


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="ptg", description="A seeded dungeon crawl narrated by a language model.")
    parser.add_argument("--seed", type=int, help="dungeon seed (same seed, same dungeon)")
    parser.add_argument("--daily", action="store_true", help="today's daily descent (same for everyone)")
    parser.add_argument("--continue", dest="resume", action="store_true", help="resume the autosave")
    parser.add_argument("--setup", action="store_true", help="open the settings screen first")
    parser.add_argument("--plain", action="store_true", help="plain text mode, no full-screen UI")
    parser.add_argument("--offline", action="store_true", help="play without a language model")
    parser.add_argument("--backend", choices=["openai", "anthropic", "offline"], help="override the narrator backend")
    parser.add_argument("--url", help="OpenAI-compatible server URL, e.g. http://localhost:1234/v1")
    parser.add_argument("--model", help="model name (default: whatever the server has loaded)")
    parser.add_argument("--name", help="your character's name")
    parser.add_argument("--event", metavar="ID", help="fire a story event right after the opening (to test it)")
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
            asyncio.run(play_plain(config or Config(url=DEFAULT_URLS["lmstudio"]), args.seed, args.resume, args.daily,
                                   args.event))
        except (KeyboardInterrupt, EOFError):
            print("\nGame saved. Bye.")
        return
    from .ui.app import PTGApp

    PTGApp(config, seed=args.seed, setup=args.setup, resume=args.resume, daily=args.daily, event=args.event).run()


def show_portrait(game: Game) -> None:
    """Print the monster's sprite when a fight starts (needs a terminal with 24-bit colour)."""
    from rich.console import Console

    from .sprites import sprite_text

    monster = game.state.room.monster
    art = sprite_text(monster.key)
    if art is not None:
        print()
        Console(highlight=False).print(art)
        print(f"  {monster.name}")


PLAIN_HELP = "Type a number or anything you like. Also: map, look, inv, char, help, quit."


def print_story(events) -> None:
    """Story cards in a frame, and what they did."""
    for event in events:
        if event.kind == "story" and event.data.get("voice") == "exact":
            title = event.data.get("title", "")
            print(f"\n  ╔═ ✧ {title} " + "═" * max(4, 60 - len(title)))
            for paragraph in event.text.split("\n\n"):
                for line in textwrap.wrap(paragraph, 64):
                    print(f"  ║ {line}")
            print("  ╚" + "═" * 66)
        elif event.kind == "story_effect" and event.text:
            print(f"  ◆ {event.text}")
        elif event.kind == "story_secret" and not event.data.get("repeat"):
            print(f"  ✧ {event.text}")


async def play_plain(config: Config, seed: int | None, resume: bool, daily: bool = False,
                     event: str | None = None) -> None:
    llm = make_llm(config)
    if llm is not None:
        try:
            await llm.prepare()
            print(f"[narrator: {llm.name}]")
        except LLMError as e:
            print(f"[no narrator: {e}. Playing offline.]")
            llm = None
    profile = Profile.open()
    content = load_content()
    state = load_game() if resume else None
    fresh = state is None
    if fresh:
        state = start_run(profile, content, config.player_name, seed=seed, daily=daily)
    game = Game(state, config, llm, content, profile)
    game.force_event = event if fresh else None
    print(f"\n=== {game.theme.name} (seed {state.seed}) · ☽ {profile.souls} souls banked ===\n{PLAIN_HELP}\n")

    def write(chunk: str) -> None:
        sys.stdout.write(chunk)
        sys.stdout.flush()

    if fresh:
        await intro(llm, state.player.name, game.theme.name, write)
        print("\n")
        print_story((await game.opening(write)).events)
    else:
        print("Previously… " + await game.recap())
    try:
        while not game.state.over:
            await game.refresh_suggestion()
            p = game.state.player
            print(f"\n\n♥ {p.hp}/{p.max_hp}  ✦ {p.fate}  ¤ {p.gold}  ☽ {game.state.souls}  Lv {p.level}  "
                  f"Floor {game.state.floor}/{game.state.floors_total}")
            for i, action in enumerate(game.choices(), 1):
                hint = f"  [{action.hint}]" if action.hint else ""
                print(f"  {i}. {action.label}{hint}")
            raw = input("> ").strip()
            command = raw.lower()
            if command in ("quit", "exit"):
                print("Game saved.")
                return
            if command in ("map", "m"):
                print("\n".join(render_map(game.state)))
                continue
            if command in ("look", "l"):
                print("\n".join(plain_lines(game.state, content)))
                continue
            if command in ("inv", "i", "inventory"):
                print(", ".join(content.item(k).name for k in [p.weapon, p.armor, *p.inventory] if k))
                continue
            if command in ("char", "c"):
                print(f"Perks: {', '.join(p.perks) or '-'}  Traits: {', '.join(p.traits) or '-'}")
                continue
            if command in ("help", "?"):
                print(PLAIN_HELP)
                continue
            if not raw:
                continue
            in_combat = game.state.in_combat
            pending = await game.begin(raw)
            while game.can_reroll():
                print(f"  [{pending.primary.roll}]")
                answer = input(f"  Failed. Spend Fate to reroll? ({game.fate_left()} left) [y/N] ")
                if answer.strip().lower() != "y":
                    break
                pending = game.reroll()
            for event in pending.events:
                if event.roll:
                    print(f"  [{event.roll}]")
            result = await game.finish(write)
            print_story(result.events)
            for error in result.errors:
                print(f"\n  ({error})")
            if game.state.in_combat and not in_combat and config.art == "sprites":
                show_portrait(game)
        print("\n\n" + share_card(game.state))
        print(f"\nSouls banked: ☽ {profile.souls}. Spend them at the campfire: run `ptg` without --plain.")
    finally:
        await game.aclose()
