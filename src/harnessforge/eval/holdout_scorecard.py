"""Aggregate disjoint Terminal-Bench holdout shards into one audited scorecard.

The TB runner writes one crash-safe JSONL file per run directory. Holdout runs
may be split into shards or repetitions to control cost and recover from API
failures, so reporting must validate that every pinned task has exactly the
declared number of independent outcomes before computing a headline metric.

Usage:
    python -m harnessforge.eval.holdout_scorecard \
      runs/tb_holdout_v1_verifier_pilot \
      runs/tb_holdout_v1_verifier_confirmation \
      runs/tb_holdout_v1_verifier_repeat2 \
      --out runs/tb_holdout_v1_verifier_scorecard.json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .stats import wilson_interval
from .tb_adapter import TB_HOLDOUT_V1


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_rows(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "results.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"missing results: {path}")
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _only(values: set[Any], label: str) -> Any:
    if len(values) != 1:
        raise ValueError(f"mixed {label}: {sorted(values, key=str)}")
    return next(iter(values))


def aggregate_holdout(
    run_dirs: list[Path],
    expected_tasks: list[str] | None = None,
    expected_repeats: int = 2,
) -> dict[str, Any]:
    expected_tasks = list(expected_tasks or TB_HOLDOUT_V1)
    if expected_repeats <= 0:
        raise ValueError("expected_repeats must be positive")
    if len(set(expected_tasks)) != len(expected_tasks):
        raise ValueError("expected_tasks contains duplicates")

    manifests = [_read_json(Path(run_dir) / "manifest.json") for run_dir in run_dirs]
    rows = [row for run_dir in run_dirs for row in _read_rows(Path(run_dir))]
    infra = [row for row in rows if row.get("exit_reason") == "infra_error"]
    if infra:
        raise ValueError(
            f"holdout is incomplete: {len(infra)} infra_error outcome(s); resume first"
        )

    task_set = set(expected_tasks)
    unknown = sorted({row["task_id"] for row in rows} - task_set)
    if unknown:
        raise ValueError(f"unexpected holdout tasks: {unknown}")
    by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_task[row["task_id"]].append(row)
    wrong_counts = {
        task: len(by_task[task])
        for task in expected_tasks
        if len(by_task[task]) != expected_repeats
    }
    if wrong_counts:
        raise ValueError(
            f"expected {expected_repeats} outcomes per task, found {wrong_counts}"
        )

    run_ids = [row["run_id"] for row in rows]
    if len(set(run_ids)) != len(run_ids):
        raise ValueError("duplicate run_id across holdout shards")

    harness_version = _only(
        {row["harness_version"] for row in rows}, "harness versions"
    )
    agent_model = _only({manifest["agent_model"] for manifest in manifests}, "models")
    max_steps = _only({manifest["max_steps"] for manifest in manifests}, "step budgets")
    temperature = _only(
        {manifest.get("temperature") for manifest in manifests}, "temperatures"
    )
    max_cost_usd = _only(
        {
            manifest.get("extra", {}).get("max_cost_usd_per_task")
            for manifest in manifests
        },
        "cost budgets",
    )
    max_output_tokens = _only(
        {
            manifest.get("extra", {}).get(
                "max_output_tokens_per_call",
                manifest.get("max_output_tokens", 4096),
            )
            for manifest in manifests
        },
        "per-call output-token budgets",
    )
    tb_revision = _only(
        {
            manifest.get("extra", {}).get("terminal_bench_revision")
            for manifest in manifests
        },
        "Terminal-Bench revisions",
    )

    passed = sum(bool(row["passed"]) for row in rows)
    n = len(rows)
    ci_low, ci_high = wilson_interval(passed, n)
    per_task = {
        task: [bool(row["passed"]) for row in by_task[task]]
        for task in expected_tasks
    }
    pass_counts = {task: sum(outcomes) for task, outcomes in per_task.items()}

    return {
        "schema_version": 1,
        "benchmark": "Terminal-Bench 2.0 holdout-v1",
        "scope": (
            f"{len(expected_tasks)} pinned holdout tasks x {expected_repeats} "
            "independent runs; not an official full-suite score"
        ),
        "harness_version": harness_version,
        "agent_model": agent_model,
        "terminal_bench_revision": tb_revision,
        "protocol": {
            "max_steps": max_steps,
            "max_tokens_per_call": max_output_tokens,
            "max_cost_usd_per_task": max_cost_usd,
            "temperature": temperature,
        },
        "task_count": len(expected_tasks),
        "repeats_per_task": expected_repeats,
        "scored_runs": n,
        "passed_runs": passed,
        "pass_rate": round(passed / n, 4),
        "wilson_95": [round(ci_low, 4), round(ci_high, 4)],
        "infra_errors": 0,
        "total_cost_usd": round(sum(row["cost_usd"] for row in rows), 4),
        "mean_cost_usd": round(sum(row["cost_usd"] for row in rows) / n, 4),
        "total_tokens": sum(row["tokens"] for row in rows),
        "mean_tokens": round(sum(row["tokens"] for row in rows) / n, 1),
        "mean_steps": round(sum(row["steps"] for row in rows) / n, 2),
        "exit_reasons": dict(sorted(Counter(row["exit_reason"] for row in rows).items())),
        "stability": {
            "stable_pass_2_of_2": sum(count == expected_repeats for count in pass_counts.values()),
            "mixed_1_of_2": sum(0 < count < expected_repeats for count in pass_counts.values()),
            "stable_fail_0_of_2": sum(count == 0 for count in pass_counts.values()),
        },
        "per_task": per_task,
        "source_run_dirs": [str(Path(run_dir)) for run_dir in run_dirs],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dirs", nargs="+", type=Path)
    parser.add_argument("--expected-repeats", type=int, default=2)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    scorecard = aggregate_holdout(
        args.run_dirs,
        expected_repeats=args.expected_repeats,
    )
    payload = json.dumps(scorecard, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload + "\n", encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
