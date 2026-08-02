"""Thin wrapper around the Anthropic API with retries, token and cost accounting.

Kept deliberately minimal: no framework, direct API calls. Pricing table must be
kept in sync manually — cost numbers feed the dashboard and per-task budget caps.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Any

import anthropic
from dotenv import load_dotenv

load_dotenv()  # picks up .env from the repo root / cwd

# USD per million tokens (input, output). Update when pricing changes.
PRICING = {
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    "claude-3-5-haiku-20241022": (0.80, 4.00),
    "claude-sonnet-5": (3.00, 15.00),
}


class LLMError(RuntimeError):
    """Base error after the client has applied its retry policy."""


class UnretryableLLMError(LLMError):
    """A request failed in a way that another attempt cannot repair."""


def is_retryable_error(error: Exception) -> bool:
    if isinstance(error, (anthropic.APIConnectionError, anthropic.APITimeoutError)):
        return True
    if isinstance(error, anthropic.APIStatusError):
        return error.status_code in {408, 409, 429} or error.status_code >= 500
    return False


def configured_temperature() -> float | None:
    """Return the explicitly configured sampling temperature, if any.

    `None` deliberately means "provider default"; manifests record that fact
    instead of claiming a seed or temperature that was never sent to the API.
    """
    raw = os.environ.get("AGENT_TEMPERATURE")
    return float(raw) if raw is not None else None


def pricing_revision() -> str:
    """Content fingerprint for the manual pricing snapshot used in accounting."""
    payload = json.dumps(PRICING, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[dict[str, Any]]  # [{id, name, input}]
    stop_reason: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    raw_content: list[Any] = field(default_factory=list)  # pass back verbatim in history


class LLMClient:
    def __init__(self, model: str | None = None, max_attempts: int = 5, backoff_s: float = 4.0,
                 timeout_s: float = 120.0, temperature: float | None = None):
        self.model = model or os.environ.get("AGENT_MODEL", "claude-haiku-4-5-20251001")
        self.provider = "anthropic"
        self.temperature = configured_temperature() if temperature is None else temperature
        # Explicit timeout, and our own retry loop (SDK retries disabled so the
        # two don't compound into multi-minute silent hangs).
        self.client = anthropic.AsyncAnthropic(timeout=timeout_s, max_retries=0)
        self.max_attempts = max_attempts
        self.backoff_s = backoff_s

    def _cost(self, tokens_in: int, tokens_out: int) -> float:
        p_in, p_out = PRICING.get(self.model, (0.0, 0.0))
        return (tokens_in * p_in + tokens_out * p_out) / 1_000_000

    async def complete(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        last_err: Exception | None = None
        for attempt in range(self.max_attempts):
            try:
                request: dict[str, Any] = {
                    "model": self.model,
                    "system": system,
                    "messages": messages,
                    "tools": tools or [],
                    "max_tokens": max_tokens,
                }
                if self.temperature is not None:
                    request["temperature"] = self.temperature
                resp = await self.client.messages.create(
                    **request,
                )
                text = "".join(b.text for b in resp.content if b.type == "text")
                tool_calls = [
                    {"id": b.id, "name": b.name, "input": b.input}
                    for b in resp.content
                    if b.type == "tool_use"
                ]
                return LLMResponse(
                    text=text,
                    tool_calls=tool_calls,
                    stop_reason=resp.stop_reason or "",
                    tokens_in=resp.usage.input_tokens,
                    tokens_out=resp.usage.output_tokens,
                    cost_usd=self._cost(resp.usage.input_tokens, resp.usage.output_tokens),
                    raw_content=[
                        block.model_dump(mode="json")
                        if hasattr(block, "model_dump") else block
                        for block in resp.content
                    ],
                )
            except (anthropic.APIStatusError, anthropic.APIConnectionError,
                    anthropic.APITimeoutError) as e:
                last_err = e
                print(f"[llm] attempt {attempt + 1}/{self.max_attempts} failed: "
                      f"{type(e).__name__}: {str(e)[:200]}", flush=True)
                if not is_retryable_error(e):
                    raise UnretryableLLMError(
                        f"unretryable LLM error: {type(e).__name__}: {e}"
                    ) from e
                if attempt + 1 >= self.max_attempts:
                    break
                # Exponential backoff with jitter: flaky networks recover better
                # when retries don't arrive in lockstep.
                import random
                await asyncio.sleep(self.backoff_s * (2 ** attempt) * (0.5 + random.random()))
        raise LLMError(
            f"LLM call failed after {self.max_attempts} attempts: "
            f"{type(last_err).__name__}: {last_err}"
        ) from last_err
