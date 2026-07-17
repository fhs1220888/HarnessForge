"""Context compaction. FIXED runtime code in v1; its knobs live in
loop_policy.yaml (context.*) so the self-harness loop can tune them.

Strategy "truncate_old_tool_results" (deterministic, zero-cost):
keep the most recent N tool_result blocks verbatim; older ones are replaced
with a short stub. Assistant tool_use blocks and user text are untouched, so
the conversation stays structurally valid for the API.
"""

from __future__ import annotations

import json
from typing import Any

STUB_KEEP_CHARS = 200


def estimate_tokens(messages: list[dict[str, Any]]) -> int:
    """Cheap heuristic: ~4 chars per token over the serialized messages."""
    try:
        return len(json.dumps(messages, ensure_ascii=False, default=str)) // 4
    except (TypeError, ValueError):
        return sum(len(str(m)) for m in messages) // 4


def _is_tool_result_block(block: Any) -> bool:
    return isinstance(block, dict) and block.get("type") == "tool_result"


def _as_text(content: Any) -> str:
    return content if isinstance(content, str) else json.dumps(content, default=str)


def _stub(content: Any) -> str:
    text = _as_text(content)
    head = text[:STUB_KEEP_CHARS]
    return f"[compacted tool result, {len(text)} chars. head: {head!r}]"


def _worth_compacting(content: Any) -> bool:
    """A stub carries ~STUB_KEEP_CHARS of head plus framing; replacing content
    shorter than that would *grow* the context. Skip those."""
    return len(_as_text(content)) > STUB_KEEP_CHARS + 48


def compact_messages(messages: list[dict[str, Any]], keep_last_n: int = 5,
                     ) -> tuple[list[dict[str, Any]], int, int]:
    """Return (compacted_messages, tokens_before, tokens_after).

    Non-destructive: builds new message/block objects where changed.
    """
    tokens_before = estimate_tokens(messages)

    # Index every tool_result block, newest last.
    locations: list[tuple[int, int]] = []  # (message_idx, block_idx)
    for mi, msg in enumerate(messages):
        content = msg.get("content")
        if isinstance(content, list):
            for bi, block in enumerate(content):
                if _is_tool_result_block(block):
                    locations.append((mi, bi))

    to_compact = set(locations[:-keep_last_n]) if keep_last_n > 0 else set(locations)
    if not to_compact:
        return messages, tokens_before, tokens_before

    new_messages: list[dict[str, Any]] = []
    for mi, msg in enumerate(messages):
        content = msg.get("content")
        if not isinstance(content, list):
            new_messages.append(msg)
            continue
        new_content = []
        for bi, block in enumerate(content):
            if ((mi, bi) in to_compact
                    and not str(block.get("content", "")).startswith("[compacted")
                    and _worth_compacting(block.get("content", ""))):
                new_block = dict(block)
                new_block["content"] = _stub(block.get("content", ""))
                new_content.append(new_block)
            else:
                new_content.append(block)
        new_messages.append({**msg, "content": new_content})

    return new_messages, tokens_before, estimate_tokens(new_messages)
