"""Claude through the official Anthropic SDK (pip install 'ptg[claude]')."""

from __future__ import annotations

import json
from typing import AsyncIterator

from ..config import DEFAULT_CLAUDE_MODEL
from .base import LLMError, log_exchange

# If a turn is declined by a safety classifier, the API re-runs it on a suitable fallback model.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicLLM:
    def __init__(self, model: str = "", api_key: str = "", temperature: float = 0.8):
        try:
            import anthropic
        except ImportError as e:
            raise LLMError("the Claude backend needs the anthropic package: uv sync --extra claude") from e
        self._anthropic = anthropic
        self.model = model or DEFAULT_CLAUDE_MODEL
        # With no key, the SDK resolves ANTHROPIC_API_KEY or an `ant auth login` profile itself.
        self.client = anthropic.AsyncAnthropic(api_key=api_key or None)

    @property
    def name(self) -> str:
        return self.model

    async def prepare(self) -> None:
        try:
            await self.client.models.retrieve(self.model)
        except self._anthropic.AuthenticationError as e:
            raise LLMError("Claude rejected the API key (set ANTHROPIC_API_KEY or run `ant auth login`)") from e
        except self._anthropic.NotFoundError as e:
            raise LLMError(f"unknown Claude model {self.model!r}") from e
        except self._anthropic.APIConnectionError as e:
            raise LLMError(f"can't reach the Claude API: {e}") from e
        except self._anthropic.APIStatusError as e:
            raise LLMError(f"Claude API error {e.status_code}: {e.message}") from e

    async def complete_json(self, system: str, user: str, schema: dict, max_tokens: int = 500) -> dict:
        request = dict(
            model=self.model,
            max_tokens=max_tokens + 4000,  # thinking is always on; leave it room
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
        )
        try:
            response = await self.client.beta.messages.create(**request, betas=[FALLBACK_BETA], fallbacks="default")
        except self._anthropic.APIError as e:
            raise LLMError(f"Claude request failed: {e}") from e
        if response.stop_reason == "refusal":
            raise LLMError("Claude declined to interpret that")
        text = next((b.text for b in response.content if b.type == "text"), "")
        log_exchange("json", request, text)
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise LLMError(f"Claude returned invalid JSON (stop_reason={response.stop_reason})") from e

    async def stream_text(self, system: str, user: str, max_tokens: int = 600) -> AsyncIterator[str]:
        request = dict(
            model=self.model,
            max_tokens=max_tokens + 4000,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": "low"},
        )
        parts: list[str] = []
        try:
            async with self.client.beta.messages.stream(**request, betas=[FALLBACK_BETA], fallbacks="default") as stream:
                async for text in stream.text_stream:
                    parts.append(text)
                    yield text
        except self._anthropic.APIError as e:
            raise LLMError(f"Claude stream failed: {e}") from e
        log_exchange("stream", request, "".join(parts))

    async def aclose(self) -> None:
        await self.client.close()
