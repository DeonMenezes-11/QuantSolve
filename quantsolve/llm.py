"""Thin OpenAI chat wrapper: JSON mode, a simple retry, token and cost accounting."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from functools import lru_cache

from .config import Settings

# USD per 1M tokens (input, output). Unknown models are costed at gpt-4.1-mini rates.
PRICES_PER_M = {"gpt-4.1-mini": (0.40, 1.60), "gpt-4o-mini": (0.15, 0.60)}


class LLMError(RuntimeError):
    """The model could not be reached or did not return a JSON object."""


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0
    cost_usd: float = 0.0

    def add(self, model: str, prompt_tokens: int, completion_tokens: int) -> None:
        price_in, price_out = PRICES_PER_M.get(model, PRICES_PER_M["gpt-4.1-mini"])
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens
        self.calls += 1
        self.cost_usd += (prompt_tokens * price_in + completion_tokens * price_out) / 1e6

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def to_dict(self) -> dict:
        data = asdict(self)
        data["cost_usd"] = round(self.cost_usd, 6)
        data["total_tokens"] = self.total_tokens
        return data


@lru_cache(maxsize=1)
def _client():
    from openai import OpenAI  # imported lazily: sandbox children never need it

    return OpenAI(timeout=60.0, max_retries=0)  # reads OPENAI_API_KEY from the environment


def chat_json(system: str, user: str, settings: Settings, usage: Usage, *,
              temperature: float | None = None) -> dict:
    """One chat completion in JSON mode; returns the parsed object."""
    from openai import APIConnectionError, APITimeoutError, InternalServerError, RateLimitError

    transient = (APIConnectionError, APITimeoutError, InternalServerError, RateLimitError)
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    last_error: Exception | None = None
    for attempt in range(1, settings.llm_retries + 1):
        try:
            response = _client().chat.completions.create(
                model=settings.model,
                messages=messages,
                temperature=settings.temperature if temperature is None else temperature,
                max_tokens=settings.max_tokens,
                response_format={"type": "json_object"},
            )
        except transient as exc:
            last_error = exc
            time.sleep(2 ** attempt)
            continue
        if response.usage:
            usage.add(settings.model, response.usage.prompt_tokens, response.usage.completion_tokens)
        text = response.choices[0].message.content or ""
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:  # e.g. output cut off at max_tokens: ask again
            last_error = exc
            continue
        if isinstance(data, dict):
            return data
        last_error = LLMError(f"expected a JSON object, got {type(data).__name__}")
    raise LLMError(f"LLM call failed after {settings.llm_retries} attempts: {last_error}")
