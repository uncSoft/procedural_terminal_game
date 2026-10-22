"""Language model backends. The game only needs two things from a model: structured JSON and streamed prose."""

from __future__ import annotations

from ..config import Config
from .base import LLM, LLMError


def make_llm(config: Config) -> LLM | None:
    """Build the configured backend, or None for offline play."""
    if config.backend == "offline":
        return None
    if config.backend == "anthropic":
        from .anthropic_backend import AnthropicLLM

        return AnthropicLLM(model=config.model, api_key=config.api_key, temperature=config.temperature)
    from .openai_compat import OpenAICompatLLM

    return OpenAICompatLLM(url=config.url, model=config.model, api_key=config.api_key, temperature=config.temperature)


__all__ = ["LLM", "LLMError", "make_llm"]
