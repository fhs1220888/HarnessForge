"""Aggregate durable-runtime evidence from one or more run directories."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ..trace import load_trace


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = round((len(ordered) - 1) * q)
    return ordered[index]


def recovery_report(run_dirs: list[Path]) -> dict[str, Any]:
    durations: list[float] = []
    snapshot_bytes: list[int] = []
    n_traces = 0
    n_resumes = 0
    n_forks = 0
    n_injected_crashes = 0
    resume_prefix_tokens = 0
    resume_prefix_cost = 0.0
    fork_prefix_tokens = 0
    fork_prefix_cost = 0.0

    for run_dir in run_dirs:
        for trace_path in sorted((Path(run_dir) / "traces").glob("*.jsonl")):
            n_traces += 1
            for event in load_trace(trace_path):
                payload = event.get("payload", {})
                if event["event_type"] == "checkpoint":
                    durations.append(float(payload.get("duration_s", 0.0)))
                    snapshot_bytes.append(int(payload.get("snapshot_bytes", 0)))
                elif event["event_type"] == "resume":
                    n_resumes += 1
                    resume_prefix_tokens += int(payload.get("tokens_in", 0))
                    resume_prefix_tokens += int(payload.get("tokens_out", 0))
                    resume_prefix_cost += float(payload.get("cost_usd", 0.0))
                elif event["event_type"] == "fork":
                    n_forks += 1
                    fork_prefix_tokens += int(payload.get("prefix_tokens_in", 0))
                    fork_prefix_tokens += int(payload.get("prefix_tokens_out", 0))
                    fork_prefix_cost += float(payload.get("prefix_cost_usd", 0.0))
                elif event["event_type"] == "fault_injected":
                    n_injected_crashes += 1

    return {
        "n_traces": n_traces,
        "n_checkpoints": len(durations),
        "n_resumes": n_resumes,
        "n_forks": n_forks,
        "n_injected_crashes": n_injected_crashes,
        "checkpoint_latency_ms": {
            "p50": round(_percentile(durations, 0.50) * 1000, 3),
            "p95": round(_percentile(durations, 0.95) * 1000, 3),
            "max": round(max(durations, default=0.0) * 1000, 3),
        },
        "snapshot_bytes": {
            "p50": int(_percentile(snapshot_bytes, 0.50)),
            "p95": int(_percentile(snapshot_bytes, 0.95)),
            "max": max(snapshot_bytes, default=0),
        },
        "fork_prefix_reuse": {
            "tokens": fork_prefix_tokens,
            "cost_usd": round(fork_prefix_cost, 6),
        },
        "resume_prefix_reuse": {
            "tokens": resume_prefix_tokens,
            "cost_usd": round(resume_prefix_cost, 6),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dirs", nargs="+", type=Path)
    args = parser.parse_args()
    print(json.dumps(recovery_report(args.run_dirs), indent=2))


if __name__ == "__main__":
    main()
