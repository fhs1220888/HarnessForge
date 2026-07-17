"""Malformed-structured-output recovery for meta-layer LLM calls.

The agent loop already has arg-level recovery (agent/validation.py rejects bad
tool args with a repair message). This is the counterpart for the mining/proposal
side, where the model must emit a JSON array: instead of silently dropping the
whole batch on a parse failure (the old `except: pass`), we send the model its
own output back with the exact parse/validation error and let it repair itself —
once by default, bounded always.

Two failure levels are handled:
- array level: the text contains no parseable JSON array
- item level: the array parses but items fail schema validation (e.g. pydantic)

On the final attempt, valid items are salvaged and bad ones dropped — a partial
batch beats an empty one. Every attempt is recorded so callers can log it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

REPAIR_PROMPT = """\
Your previous output could not be used:
{error}

Reply with ONLY a corrected JSON array (no prose, no markdown fences), fixing
exactly the problems listed above and changing nothing else.
"""


@dataclass
class StructuredResult:
    items: list[Any] = field(default_factory=list)
    llm_calls: int = 0
    repaired: bool = False          # a repair round-trip happened and succeeded
    errors: list[str] = field(default_factory=list)  # one entry per failed attempt

    @property
    def ok(self) -> bool:
        return bool(self.items)


def extract_json_array(text: str) -> list[Any]:
    """Parse the outermost JSON array in `text`; raise ValueError with a message
    precise enough for the model to act on."""
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end <= start:
        raise ValueError("no JSON array found in the output (expected '[...]')")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON array does not parse: {e}") from None
    if not isinstance(data, list):
        raise ValueError(f"expected a JSON array, got {type(data).__name__}")
    return data


async def complete_json_array(
    llm: Any,
    system: str,
    prompt: str,
    *,
    max_tokens: int = 4096,
    repair_attempts: int = 1,
    item_parser: Callable[[dict[str, Any]], Any] | None = None,
) -> StructuredResult:
    """Ask `llm` for a JSON array; on malformed output, retry with a repair
    message quoting the exact error. `item_parser` (e.g. a pydantic constructor)
    upgrades item-level validation failures into repairable errors too.
    """
    result = StructuredResult()
    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]

    for attempt in range(repair_attempts + 1):
        final = attempt == repair_attempts
        resp = await llm.complete(system=system, messages=messages, max_tokens=max_tokens)
        result.llm_calls += 1

        try:
            raw_items = extract_json_array(resp.text)
        except ValueError as e:
            result.errors.append(str(e))
            if final:
                return result
            messages.append({"role": "assistant", "content": resp.text or "..."})
            messages.append({"role": "user", "content": REPAIR_PROMPT.format(error=e)})
            continue

        if item_parser is None:
            result.items = raw_items
            result.repaired = attempt > 0
            return result

        parsed, item_errors = [], []
        for i, item in enumerate(raw_items):
            try:
                parsed.append(item_parser(item))
            except Exception as e:  # pydantic ValidationError, KeyError, ...
                item_errors.append(f"item {i}: {e}")

        if not item_errors or final:
            # clean parse, or last chance: salvage what's valid.
            result.items = parsed
            result.errors.extend(item_errors)
            result.repaired = attempt > 0 and bool(parsed)
            return result

        err = "; ".join(item_errors)
        result.errors.append(err)
        messages.append({"role": "assistant", "content": resp.text or "..."})
        messages.append({"role": "user", "content": REPAIR_PROMPT.format(error=err)})

    return result  # pragma: no cover (loop always returns)
