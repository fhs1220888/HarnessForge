"""Exact, resume-safe usage accounting for Self-Harness campaigns.

Agent calls are already durable in trace ``llm_response`` events. Meta-layer
miner/proposer calls are recorded separately in each round's ``meta_usage.json``.
Keeping the two ledgers disjoint lets a campaign report actual new spend without
double-counting a reused baseline or a previous round's final evaluation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


def empty_usage() -> dict[str, int | float]:
    return {
        "model_calls": 0,
        "tokens_in": 0,
        "tokens_out": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
    }


def normalized_usage(value: Mapping[str, Any] | None) -> dict[str, int | float]:
    value = value or {}
    tokens_in = int(value.get("tokens_in", 0))
    tokens_out = int(value.get("tokens_out", 0))
    return {
        "model_calls": int(value.get("model_calls", value.get("llm_calls", 0))),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "total_tokens": tokens_in + tokens_out,
        "cost_usd": round(float(value.get("cost_usd", 0.0)), 6),
    }


def combine_usage(*values: Mapping[str, Any] | None) -> dict[str, int | float]:
    total = empty_usage()
    for value in values:
        usage = normalized_usage(value)
        total["model_calls"] += int(usage["model_calls"])
        total["tokens_in"] += int(usage["tokens_in"])
        total["tokens_out"] += int(usage["tokens_out"])
        total["cost_usd"] += float(usage["cost_usd"])
    total["total_tokens"] = int(total["tokens_in"]) + int(total["tokens_out"])
    total["cost_usd"] = round(float(total["cost_usd"]), 6)
    return total


def add_usage(target: dict[str, int | float], value: Mapping[str, Any]) -> None:
    """Mutate an existing normalized ledger with one additional usage record."""
    target.update(combine_usage(target, value))


def trace_usage(root: Path) -> dict[str, int | float]:
    """Sum exact agent usage from every trace below ``root``."""
    total = empty_usage()
    root = Path(root)
    if not root.exists():
        return total
    for trace_path in root.rglob("*.jsonl"):
        if trace_path.parent.name != "traces":
            continue
        with trace_path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                event = json.loads(line)
                if event.get("event_type") != "llm_response":
                    continue
                add_usage(total, {
                    "model_calls": 1,
                    "tokens_in": event.get("tokens_in", 0),
                    "tokens_out": event.get("tokens_out", 0),
                    "cost_usd": event.get("cost_usd", 0.0),
                })
    return total


def meta_usage(root: Path) -> dict[str, int | float]:
    """Sum round-local meta ledgers, including archived interrupted rounds."""
    total = empty_usage()
    root = Path(root)
    if not root.exists():
        return total
    for usage_path in root.rglob("meta_usage.json"):
        payload = json.loads(usage_path.read_text(encoding="utf-8"))
        add_usage(total, payload.get("total", payload))
    return total


def campaign_usage(root: Path) -> dict[str, Any]:
    agent = trace_usage(root)
    meta = meta_usage(root)
    return {"agent": agent, "meta": meta, "total": combine_usage(agent, meta)}
