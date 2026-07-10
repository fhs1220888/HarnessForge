"""Thin wrapper around the Anthropic API with retries, token and cost accounting.

Kept deliberately minimal: no framework, direct API calls. Pricing table must be
kept in sync manually — cost numbers feed the dashboard and per-task budget caps.
"""

from __future__ import annotations

import asyncio
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
                 timeout_s: float = 120.0):
        self.model = model or os.environ.get("AGENT_MODEL", "claude-haiku-4-5-20251001")
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
                resp = await self.client.messages.create(
                    model=self.model,
                    system=system,
                    messages=messages,
                    tools=tools or [],
                    max_tokens=max_tokens,
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
                    raw_content=resp.content,
                )
            except (anthropic.APIStatusError, anthropic.APIConnectionError,
                    anthropic.APITimeoutError) as e:
                last_err = e
                print(f"[llm] attempt {attempt + 1}/{self.max_attempts} failed: "
                      f"{type(e).__name__}: {str(e)[:200]}", flush=True)
                if isinstance(e, anthropic.NotFoundError):
                    break  # unknown model — retrying won't help
                # Exponential backoff with jitter: flaky networks recover better
                # when retries don't arrive in lockstep.
                import random
                await asyncio.sleep(self.backoff_s * (2 ** attempt) * (0.5 + random.random()))
        raise RuntimeError(
            f"LLM call failed after {self.max_attempts} attempts: "
            f"{type(last_err).__name__}: {last_err}"
        ) from last_err
