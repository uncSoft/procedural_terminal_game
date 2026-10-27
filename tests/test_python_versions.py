"""The game runs on the oldest Python pyproject.toml allows. A Mac with Python 3.11 couldn't start it: a backslash
inside an f-string's braces is fine from 3.12 on, and a SyntaxError before. Newer Pythons can't tell, so this asks the
oldest one itself, when it's installed here to ask."""

import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHECK = """
import sys
bad = []
for path in sys.stdin.read().split("\\n"):
    try:
        compile(open(path, encoding="utf-8").read(), path, "exec")
    except SyntaxError as error:
        bad.append(f"{path}:{error.lineno}: {error.msg}")
print("\\n".join(bad))
"""


def test_every_file_compiles_on_the_oldest_python_allowed():
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["requires-python"].removeprefix(">=")
    python = shutil.which(f"python{version}")
    if python is None:
        pytest.skip(f"no python{version} here to try")
    files = [str(p) for folder in ("src", "tests", "tools") for p in sorted((ROOT / folder).rglob("*.py"))]
    result = subprocess.run([python, "-c", CHECK], input="\n".join(files), capture_output=True, text=True,
                            check=True)
    assert not result.stdout.strip(), f"won't run on Python {version}:\n{result.stdout}"
