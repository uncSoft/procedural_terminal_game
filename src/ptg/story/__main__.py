"""Check story files and list what's in them.

    uv run python -m ptg.story              # the game's own story files
    uv run python -m ptg.story drafts/      # a folder of your drafts
"""

from __future__ import annotations

import sys
from pathlib import Path

from ..content import ContentError, load_content
from ..integrity import check
from .model import StoryError
from .parser import load_folder, load_library


def main(argv: list[str]) -> int:
    try:
        content = load_content()
        library = load_folder(Path(argv[0]), content) if argv else load_library(content)
    except (ContentError, StoryError) as e:
        print(e)
        return 1
    for event in library:
        kind = "scene" if event.is_scene else "moment"
        trigger = " ".join([event.trigger, " | ".join(event.trigger_args)]).strip()
        secret = "✧ secret" if event.secret else ""
        print(f"✓ {event.id:<22} {kind:<7} when {trigger:<24} once per {event.once:<8} {secret}")
        for node in event.nodes.values():
            if node.choices:
                extra = " + catch-all" if node.fallback else ""
                print(f"      part '{node.id}': {len(node.options)} choices{extra}")
    print(f"\n{len(list(library))} story events, {len(library.secrets)} secrets. No problems found.")
    report = check()
    if report.tampered:
        print("\nThe data files have changed since they were last signed (" + "; ".join(report.lines()) + ").")
        print("When you're happy with them, sign them, or Hackerman will find you:")
        print("  uv run python -m ptg.integrity --sign")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
