"""Any server that speaks the OpenAI chat-completions API: LM Studio, Ollama, llama.cpp, vLLM, OpenRouter..."""

from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from .base import LLMError, ThinkFilter, extract_json, log_exchange


def normalize_url(url: str) -> str:
    url = url.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    return url if url.endswith("/v1") else url + "/v1"


class OpenAICompatLLM:
    def __init__(self, url: str, model: str = "", api_key: str = "", temperature: float = 0.8, timeout: float = 120):
        self.base = normalize_url(url)
        self.model = model
        self.temperature = temperature
        self.json_schema_supported = True
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.client = httpx.AsyncClient(headers=headers, timeout=httpx.Timeout(timeout, connect=5))

    @property
    def name(self) -> str:
        return f"{self.model or '?'} @ {self.base}"

    async def list_models(self) -> list[str]:
        """Chat models the server offers, loaded ones first when the server says (LM Studio does)."""
        loaded: list[str] = []
        try:
            response = await self.client.get(self.base.removesuffix("/v1") + "/api/v0/models")
            if response.status_code == 200:
                data = response.json()["data"]
                loaded = [m["id"] for m in data if m.get("state") == "loaded" and m.get("type") in ("llm", "vlm")]
        except (httpx.HTTPError, ValueError, KeyError):
            pass
        try:
            response = await self.client.get(f"{self.base}/models")
            response.raise_for_status()
            ids = [m["id"] for m in response.json()["data"]]
        except (httpx.HTTPError, ValueError, KeyError) as e:
            raise LLMError(f"can't reach {self.base}: {e}") from e
        chat = [i for i in ids if "embed" not in i.lower()]
        return loaded + [i for i in chat if i not in loaded]

    async def prepare(self) -> None:
        models = await self.list_models()
        if not self.model:
            if not models:
                raise LLMError(f"{self.base} has no chat models available")
            self.model = models[0]

    async def complete_json(self, system: str, user: str, schema: dict, max_tokens: int = 500) -> dict:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.4,
            "max_tokens": max_tokens,
        }
        if self.json_schema_supported:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "response", "strict": True, "schema": schema},
            }
        response = await self._post(payload)
        if response.status_code == 400 and self.json_schema_supported:
            # Older servers reject json_schema; fall back to asking nicely and parsing what comes back.
            self.json_schema_supported = False
            payload.pop("response_format")
            payload["messages"][0]["content"] += "\n\nReply with a single JSON object matching this schema:\n" + json.dumps(schema)
            response = await self._post(payload)
        self._raise_for_status(response)
        message = response.json()["choices"][0]["message"]
        content = message.get("content") or ""
        log_exchange("json", payload, content)
        return extract_json(content)

    async def stream_text(self, system: str, user: str, max_tokens: int = 600) -> AsyncIterator[str]:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": self.temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        think = ThinkFilter()
        parts: list[str] = []
        try:
            async with self.client.stream("POST", f"{self.base}/chat/completions", json=payload) as response:
                if response.status_code >= 400:
                    await response.aread()
                    self._raise_for_status(response)
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        delta = json.loads(data)["choices"][0]["delta"].get("content") or ""
                    except (ValueError, KeyError, IndexError):
                        continue
                    visible = think.feed(delta)
                    if visible:
                        parts.append(visible)
                        yield visible
        except httpx.HTTPError as e:
            raise LLMError(f"stream failed: {e}") from e
        tail = think.flush()
        if tail:
            parts.append(tail)
            yield tail
        log_exchange("stream", payload, "".join(parts))

    async def _post(self, payload: dict) -> httpx.Response:
        try:
            return await self.client.post(f"{self.base}/chat/completions", json=payload)
        except httpx.HTTPError as e:
            raise LLMError(f"request to {self.base} failed: {e}") from e

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.status_code >= 400:
            raise LLMError(f"HTTP {response.status_code}: {response.text[:300]}")

    async def aclose(self) -> None:
        await self.client.aclose()
