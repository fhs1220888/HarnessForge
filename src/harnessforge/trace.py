"""Trace schema and JSONL writer.

Everything downstream — weakness mining, replay, the dashboard, cost accounting —
reads this one schema. Keep it stable; add fields, don't rename them.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class EventType(str, Enum):
    RUN_START = "run_start"          # payload: task_id, harness_version, model, policy snapshot
    LLM_REQUEST = "llm_request"      # payload: messages digest, n_messages
    LLM_RESPONSE = "llm_response"    # payload: text, tool_calls; tokens/cost filled
    TOOL_CALL = "tool_call"          # payload: tool name, input
    TOOL_RESULT = "tool_result"      # payload: output (truncated), exit_code, error, duration_s
    COMPACTION = "compaction"        # payload: tokens_before, tokens_after, strategy
    TERMINATION = "termination"      # payload: exit_reason, status, summary
    TEST_RUN = "test_run"            # payload: command, passed, output (truncated)
    VALIDATION_ERROR = "validation_error"  # payload: tool, input, error (bad tool args, not executed)
    MEMORY_WRITE = "memory_write"    # payload: key, content (truncated), n_notes


# Exit reasons — the vocabulary weakness mining clusters over. Extend as needed.
EXIT_REASONS = [
    "finished_done",
    "finished_gave_up",
    "max_steps",
    "max_tokens",
    "max_cost",
    "repeated_action",
    "repeated_tool_error",
    "repeated_validation_error",
    "api_error",
    "sandbox_error",
]


@dataclass
class TraceEvent:
    run_id: str
    task_id: str
    step: int
    event_type: EventType
    payload: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0

    def to_json(self) -> str:
        d = asdict(self)
        d["event_type"] = self.event_type.value
        return json.dumps(d, ensure_ascii=False)


class TraceWriter:
    """Appends one JSON object per line to <trace_dir>/<run_id>.jsonl."""

    def __init__(self, trace_dir: Path, task_id: str, run_id: str | None = None):
        self.run_id = run_id or f"{task_id}-{uuid.uuid4().hex[:8]}"
        self.task_id = task_id
        self.path = Path(trace_dir) / f"{self.run_id}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._step = 0
        self.total_tokens_in = 0
        self.total_tokens_out = 0
        self.total_cost_usd = 0.0

    def emit(self, event_type: EventType, payload: dict[str, Any] | None = None,
             tokens_in: int = 0, tokens_out: int = 0, cost_usd: float = 0.0) -> TraceEvent:
        ev = TraceEvent(
            run_id=self.run_id, task_id=self.task_id, step=self._step,
            event_type=event_type, payload=payload or {},
            tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=cost_usd,
        )
        self._step += 1
        self.total_tokens_in += tokens_in
        self.total_tokens_out += tokens_out
        self.total_cost_usd += cost_usd
        with self.path.open("a", encoding="utf-8") as f:
            f.write(ev.to_json() + "\n")
        return ev


def load_trace(path: Path) -> list[dict[str, Any]]:
    with Path(path).open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]
