"""Notices when the game's own data files have been edited.

The shipped data files are fingerprinted in data/manifest.json. Change one, add a story file or delete
one, and the game notices: there's an entry in the Book of Secrets for that, and runs played on edited
data are marked as modded. Sprites don't count; custom art is welcome.

    uv run python -m ptg.integrity          # what's changed since the files were last signed
    uv run python -m ptg.integrity --sign   # accept the current files (after real edits, before committing)
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from pathlib import Path

MANIFEST = "manifest.json"
TRACKED = ("*.toml", "art.txt", "splash.txt", "story/*.md")


def data_folder() -> Path:
    return Path(str(resources.files("ptg") / "data"))


def fingerprints(folder: Path) -> dict[str, str]:
    """sha256 of every tracked data file, by its path inside the data folder."""
    found = {}
    for pattern in TRACKED:
        for path in sorted(folder.glob(pattern)):
            found[path.relative_to(folder).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return dict(sorted(found.items()))


@dataclass(frozen=True)
class Report:
    changed: tuple[str, ...] = ()
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    unsigned: bool = False  # the manifest itself is missing or unreadable

    @property
    def tampered(self) -> bool:
        return bool(self.changed or self.added or self.removed or self.unsigned)

    def lines(self) -> list[str]:
        if self.unsigned:
            return ["the data manifest is missing or unreadable"]
        return ([f"changed: {name}" for name in self.changed] + [f"added: {name}" for name in self.added]
                + [f"removed: {name}" for name in self.removed])


def check(folder: Path | None = None) -> Report:
    folder = folder or data_folder()
    try:
        signed = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))["files"]
    except (OSError, ValueError, KeyError, TypeError):
        return Report(unsigned=True)
    current = fingerprints(folder)
    return Report(
        changed=tuple(n for n in current if n in signed and current[n] != signed[n]),
        added=tuple(n for n in current if n not in signed),
        removed=tuple(n for n in signed if n not in current),
    )


@lru_cache(maxsize=1)
def shipped_report() -> Report:
    """The check for the installed game's own data, done once per launch."""
    return check()


def sign(folder: Path | None = None) -> Path:
    folder = folder or data_folder()
    path = folder / MANIFEST
    manifest = {"note": "Fingerprints of the shipped data. Editing the data is allowed, and noticed.",
                "files": fingerprints(folder)}
    path.write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    shipped_report.cache_clear()
    return path


def main(argv: list[str]) -> int:
    if argv[:1] == ["--sign"]:
        path = sign()
        print(f"Signed {len(fingerprints(data_folder()))} data files into {path}.")
        return 0
    report = check()
    if not report.tampered:
        print("The data files match their signatures.")
        return 0
    print("The data files have been edited since they were signed:")
    for line in report.lines():
        print(f"  {line}")
    print("\nIf that was you making real changes, accept them with: uv run python -m ptg.integrity --sign")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
