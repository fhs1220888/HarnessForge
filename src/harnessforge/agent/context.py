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
LEDGER_START = "<budget_compaction_ledger>"
LEDGER_END = "</budget_compaction_ledger>"


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


def _tool_turn(message: dict[str, Any], result_message: dict[str, Any]) -> bool:
    if message.get("role") != "assistant" or result_message.get("role") != "user":
        return False
    calls = message.get("content")
    results = result_message.get("content")
    if not isinstance(calls, list) or not isinstance(results, list):
        return False
    call_ids = {
        block.get("id")
        for block in calls
        if isinstance(block, dict) and block.get("type") == "tool_use"
    }
    result_ids = {
        block.get("tool_use_id")
        for block in results
        if isinstance(block, dict) and block.get("type") == "tool_result"
    }
    return bool(call_ids) and call_ids == result_ids


def _short(value: Any, limit: int) -> str:
    text = value if isinstance(value, str) else json.dumps(
        value, ensure_ascii=False, default=str, separators=(",", ":")
    )
    return " ".join(text.split())[:limit]


def _ledger_entries(
    message: dict[str, Any], result_message: dict[str, Any]
) -> list[str]:
    results = {
        block["tool_use_id"]: block
        for block in result_message["content"]
        if isinstance(block, dict) and block.get("type") == "tool_result"
    }
    entries = []
    for call in message["content"]:
        if not isinstance(call, dict) or call.get("type") != "tool_use":
            continue
        result = results.get(call.get("id"), {})
        state = "error" if result.get("is_error") else "ok"
        entries.append(
            f"- {call.get('name', 'tool')}({_short(call.get('input', {}), 120)}) "
            f"-> {state}: {_short(result.get('content', ''), 100)}"
        )
    return entries


def _merge_ledger(content: str, entries: list[str], max_chars: int) -> str:
    base = content
    existing: list[str] = []
    omitted = 0
    start = content.find(LEDGER_START)
    end = content.find(LEDGER_END)
    if start >= 0 and end > start:
        base = content[:start].rstrip()
        for line in content[start + len(LEDGER_START):end].strip().splitlines():
            if line.startswith("[older compacted turns omitted: "):
                try:
                    omitted += int(line.rsplit(" ", 1)[1].rstrip("]"))
                except ValueError:
                    pass
            elif line:
                existing.append(line)

    merged = existing + entries
    while merged and len("\n".join(merged)) > max_chars:
        merged.pop(0)
        omitted += 1
    prefix = [f"[older compacted turns omitted: {omitted}]"] if omitted else []
    ledger = "\n".join(prefix + merged)
    return f"{base}\n\n{LEDGER_START}\n{ledger}\n{LEDGER_END}"


def compact_tool_turns(
    messages: list[dict[str, Any]],
    keep_last_n: int = 6,
    ledger_max_chars: int = 4000,
) -> tuple[list[dict[str, Any]], int, int, int]:
    """Collapse old tool-use/result pairs into a bounded deterministic ledger.

    Dropping the complete pair keeps Anthropic's tool-use protocol valid. The
    ledger is attached to the original task message, so old observations remain
    available without repeatedly paying for the full JSON/tool output history.
    Returns ``(messages, tokens_before, tokens_after, dropped_turns)``.
    """
    tokens_before = estimate_tokens(messages)
    if not messages or messages[0].get("role") != "user":
        return messages, tokens_before, tokens_before, 0
    initial_content = messages[0].get("content")
    if not isinstance(initial_content, str):
        return messages, tokens_before, tokens_before, 0

    pairs = [
        (index, index + 1)
        for index in range(1, len(messages) - 1)
        if _tool_turn(messages[index], messages[index + 1])
    ]
    drop = pairs[:-keep_last_n] if keep_last_n > 0 else pairs
    if not drop:
        return messages, tokens_before, tokens_before, 0

    entries = [
        entry
        for assistant_index, result_index in drop
        for entry in _ledger_entries(messages[assistant_index], messages[result_index])
    ]
    dropped_indexes = {index for pair in drop for index in pair}
    new_messages = [dict(messages[0])]
    new_messages[0]["content"] = _merge_ledger(
        initial_content, entries, max(200, ledger_max_chars)
    )
    new_messages.extend(
        message for index, message in enumerate(messages[1:], start=1)
        if index not in dropped_indexes
    )
    tokens_after = estimate_tokens(new_messages)
    if tokens_after >= tokens_before:
        return messages, tokens_before, tokens_before, 0
    return new_messages, tokens_before, tokens_after, len(drop)
