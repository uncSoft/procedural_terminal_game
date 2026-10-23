"""The interface every backend implements, plus helpers for cleaning up model output."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator, Protocol

from ..config import log_path


class LLMError(Exception):
    pass


class LLM(Protocol):
    name: str

    async def prepare(self) -> None:
        """Check the backend is reachable and pick a model if none was configured."""

    async def complete_json(self, system: str, user: str, schema: dict, max_tokens: int = 500) -> dict: ...

    def stream_text(self, system: str, user: str, max_tokens: int = 600) -> AsyncIterator[str]: ...

    async def aclose(self) -> None: ...


def extract_json(text: str) -> dict:
    """Parse a JSON object out of model output that may be wrapped in fences, think tags or chatter."""
    text = strip_think(text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fenced:
        return json.loads(fenced.group(1))
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start:end + 1])
    raise LLMError(f"no JSON object in model output: {text[:200]!r}")


def strip_think(text: str) -> str:
    return re.sub(r"<think>.*?(</think>|$)", "", text, flags=re.S)


class ThinkFilter:
    """Drops <think>...</think> spans from a token stream, even when the tags arrive split across chunks."""

    def __init__(self) -> None:
        self.buffer = ""
        self.thinking = False

    def feed(self, chunk: str) -> str:
        self.buffer += chunk
        out = []
        while self.buffer:
            tag = "</think>" if self.thinking else "<think>"
            index = self.buffer.find(tag)
            if index == -1:
                # Hold back anything that could be the start of a tag.
                keep = next((n for n in range(len(tag) - 1, 0, -1) if self.buffer.endswith(tag[:n])), 0)
                if not self.thinking:
                    out.append(self.buffer[:len(self.buffer) - keep])
                self.buffer = self.buffer[len(self.buffer) - keep:]
                break
            if not self.thinking:
                out.append(self.buffer[:index])
            self.buffer = self.buffer[index + len(tag):]
            self.thinking = not self.thinking
        return "".join(out)

    def flush(self) -> str:
        rest, self.buffer = ("" if self.thinking else self.buffer), ""
        return rest


def log_exchange(label: str, request: object, response: object) -> None:
    try:
        with log_path().open("a", encoding="utf-8") as f:
            f.write(f"--- {datetime.now():%H:%M:%S} {label}\n")
            f.write(f">>> {json.dumps(request, indent=1, ensure_ascii=False)[:6000]}\n")
            f.write(f"<<< {response if isinstance(response, str) else json.dumps(response, ensure_ascii=False)}\n\n")
    except OSError:
        pass


@dataclass
class Exchange:
    """One entry in llm.log: what went to the model and what came back (for "guard": what it cut, and kept)."""

    time: str
    label: str
    request: object  # the request as sent (a dict), the guard's cuts (a list), or the raw text if it was cut short
    response: str


LOG_ENTRY = re.compile(r"^--- (\d\d:\d\d:\d\d) (\S+)$", re.M)


def read_log(limit: int = 80, path: Path | None = None, tail: int = 600_000) -> list[Exchange]:
    """The latest exchanges in llm.log, newest first (only the end of the file is read)."""
    try:
        with (path or log_path()).open("rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - tail))
            text = f.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    headers = list(LOG_ENTRY.finditer(text))
    found = []
    for header, after in zip(headers, headers[1:] + [None]):
        body = text[header.end():after.start() if after else len(text)]
        request, _, response = body.partition("\n<<< ")
        request = request.strip().removeprefix(">>> ")
        try:
            request = json.loads(request)
        except ValueError:
            pass
        found.append(Exchange(header.group(1), header.group(2), request, response.strip()))
    return found[::-1][:limit]
