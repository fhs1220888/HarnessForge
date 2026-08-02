"""Run resumable same-prefix counterfactuals across a task set.

The single-task counterfactual command is useful for diagnosis. This module turns
that mechanism into a benchmark: it selects a pre-outcome checkpoint per task by
a declared rule, runs every candidate from that prefix, optionally adds full-rerun
controls, and aggregates paired cost/outcome evidence.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from ..agent.checkpoint import AgentCheckpointStore
from ..trace import load_trace
from .counterfactual import (
    ARM_NAME,
    _candidate,
    _write_json_atomic,
    run_counterfactual,
)
from .stats import paired_bootstrap_continuous, wilson_interval


def select_checkpoint(
    source_run: Path,
    task_id: str,
    fraction: float = 0.5,
) -> dict[str, Any]:
    """Select a meaningful historical turn without inspecting candidate outcomes.

    We retain checkpoints with a paid prefix and no final result, then choose the
    first one at or beyond ``fraction`` of the last eligible step. The selected
    workspace snapshot must exist, making the rule safe to apply before any arm is
    evaluated.
    """
    if not 0 < fraction <= 1:
        raise ValueError("checkpoint fraction must be in (0, 1]")

    source_run = Path(source_run)
    run_key = f"{task_id}-r0"
    history_dir = source_run / "checkpoint_history" / run_key
    eligible: dict[int, dict[str, Any]] = {}
    for path in sorted(history_dir.glob("step-*.json")):
        record = AgentCheckpointStore.read(path)
        if record.next_step <= 0 or record.final_result is not None:
            continue
        if not record.workspace_snapshot:
            continue
        snapshot = source_run / "workspace_snapshots" / run_key / record.workspace_snapshot
        if not snapshot.exists():
            continue
        eligible[record.next_step] = {
            "step": record.next_step,
            "checkpoint": str(path.resolve()),
            "workspace_snapshot": record.workspace_snapshot,
            "prefix_tokens": record.tokens_in + record.tokens_out,
            "prefix_cost_usd": round(record.cost_usd, 6),
        }

    if not eligible:
        raise FileNotFoundError(
            f"no non-terminal paid checkpoint with a snapshot for {run_key}"
        )
    steps = sorted(eligible)
    target = math.ceil(steps[-1] * fraction)
    selected_step = next((step for step in steps if step >= target), steps[-1])
    return eligible[selected_step] | {
        "selection_fraction": fraction,
        "last_eligible_step": steps[-1],
    }


def _rate(successes: int, observations: int) -> dict[str, Any]:
    low, high = wilson_interval(successes, observations)
    return {
        "successes": successes,
        "observations": observations,
        "rate": round(successes / observations, 6) if observations else None,
        "wilson_ci95": [round(low, 6), round(high, 6)] if observations else None,
    }


def _source_usage(source_run: Path, task_ids: list[str]) -> dict[str, Any]:
    tokens = 0
    cost = 0.0
    observed = 0
    for task_id in task_ids:
        path = source_run / "traces" / f"{task_id}-r0.jsonl"
        if not path.exists():
            continue
        observed += 1
        for event in load_trace(path):
            if event["event_type"] == "llm_response":
                tokens += int(event.get("tokens_in", 0)) + int(event.get("tokens_out", 0))
                cost += float(event.get("cost_usd", 0.0))
    return {
        "tasks_observed": observed,
        "tokens": tokens,
        "cost_usd": round(cost, 6),
    }


def _paired_delta(
    reports: list[dict[str, Any]],
    full_key: str,
    fork_key: str,
) -> dict[str, Any]:
    full: dict[str, list[float]] = defaultdict(list)
    fork: dict[str, list[float]] = defaultdict(list)
    for report in reports:
        task_id = report["task_id"]
        for arm in report["arms"]:
            if arm["full_rerun"] is None:
                continue
            full[task_id].append(float(arm["full_rerun"]["usage"][full_key]))
            fork[task_id].append(float(arm["fork"]["continuation_usage"][fork_key]))
    if not full:
        return {}
    # Existing helper reports after-before. Here, after=fork continuation and
    # before=full rerun, so negative deltas mean savings.
    return paired_bootstrap_continuous(full, fork, seed=20260802)


def aggregate_reports(
    source_run: Path,
    reports: list[dict[str, Any]],
) -> dict[str, Any]:
    arms = [arm for report in reports for arm in report["arms"]]
    fork_passes = sum(bool(arm["fork"]["passed"]) for arm in arms)
    fork_tokens = sum(arm["fork"]["continuation_usage"]["tokens"] for arm in arms)
    fork_cost = sum(arm["fork"]["continuation_usage"]["cost_usd"] for arm in arms)
    reused_tokens = sum(arm["fork"]["prefix_reused_tokens"] for arm in arms)
    reused_cost = sum(arm["fork"]["prefix_reused_cost_usd"] for arm in arms)

    full_arms = [arm for arm in arms if arm["full_rerun"] is not None]
    full_tokens = sum(arm["full_rerun"]["usage"]["tokens"] for arm in full_arms)
    full_cost = sum(arm["full_rerun"]["usage"]["cost_usd"] for arm in full_arms)
    agreements = sum(
        arm["fork"]["passed"] == arm["full_rerun"]["passed"] for arm in full_arms
    )

    per_candidate: dict[str, dict[str, Any]] = {}
    for name in sorted({arm["name"] for arm in arms}):
        candidate_arms = [arm for arm in arms if arm["name"] == name]
        passes = sum(bool(arm["fork"]["passed"]) for arm in candidate_arms)
        per_candidate[name] = {
            "fork_outcomes": _rate(passes, len(candidate_arms)),
            "continuation_tokens": sum(
                arm["fork"]["continuation_usage"]["tokens"] for arm in candidate_arms
            ),
            "continuation_cost_usd": round(sum(
                arm["fork"]["continuation_usage"]["cost_usd"]
                for arm in candidate_arms
            ), 6),
            "mean_steps": round(sum(
                arm["fork"]["steps"] for arm in candidate_arms
            ) / len(candidate_arms), 3),
        }

    completed_task_ids = [report["task_id"] for report in reports]
    source_usage = _source_usage(Path(source_run), completed_task_ids)
    aggregate: dict[str, Any] = {
        "completed_tasks": len(reports),
        "candidate_task_observations": len(arms),
        "fork_outcomes": _rate(fork_passes, len(arms)),
        "continuation_usage": {
            "tokens": fork_tokens,
            "cost_usd": round(fork_cost, 6),
        },
        "reused_prefix": {
            "tokens": reused_tokens,
            "cost_usd": round(reused_cost, 6),
        },
        "source_run_usage": source_usage,
        "per_candidate": per_candidate,
    }

    if full_arms:
        full_passes = sum(bool(arm["full_rerun"]["passed"]) for arm in full_arms)
        token_savings = full_tokens - sum(
            arm["fork"]["continuation_usage"]["tokens"] for arm in full_arms
        )
        matched_fork_cost = sum(
            arm["fork"]["continuation_usage"]["cost_usd"] for arm in full_arms
        )
        cost_savings = full_cost - matched_fork_cost
        aggregate["full_rerun_control"] = {
            "outcomes": _rate(full_passes, len(full_arms)),
            "usage": {"tokens": full_tokens, "cost_usd": round(full_cost, 6)},
            "outcome_agreement": _rate(agreements, len(full_arms)),
            "savings": {
                "tokens": token_savings,
                "token_fraction": round(token_savings / full_tokens, 6)
                if full_tokens else None,
                "cost_usd": round(cost_savings, 6),
                "cost_fraction": round(cost_savings / full_cost, 6)
                if full_cost else None,
                "paired_continuation_minus_full_tokens": _paired_delta(
                    reports, "tokens", "tokens"
                ),
                "paired_continuation_minus_full_cost_usd": _paired_delta(
                    reports, "cost_usd", "cost_usd"
                ),
            },
        }

    aggregate["accounting"] = {
        "incremental_evaluation_cost_usd": round(fork_cost + full_cost, 6),
        "end_to_end_cost_including_source_usd": round(
            source_usage["cost_usd"] + fork_cost + full_cost, 6
        ),
        "note": (
            "Incremental evaluation includes fork continuations and optional full "
            "controls. End-to-end also includes the source trajectories that created "
            "the reusable checkpoints."
        ),
    }
    return aggregate


def _batch_report(
    source_run: Path,
    task_ids: list[str],
    candidates: dict[str, Path],
    checkpoints: dict[str, dict[str, Any]],
    reports: list[dict[str, Any]],
    *,
    sandbox_kind: str,
    include_full_rerun: bool,
    checkpoint_fraction: float,
    status: str,
    max_new_cost_usd: float | None,
) -> dict[str, Any]:
    completed = {report["task_id"] for report in reports}
    return {
        "schema_version": 1,
        "benchmark": "multitask-same-prefix-counterfactual",
        "status": status,
        "source_run": str(Path(source_run).resolve()),
        "task_ids_requested": task_ids,
        "task_ids_completed": [task_id for task_id in task_ids if task_id in completed],
        "task_ids_pending": [task_id for task_id in task_ids if task_id not in completed],
        "candidates": {name: str(Path(path).resolve()) for name, path in candidates.items()},
        "sandbox": sandbox_kind,
        "include_full_rerun": include_full_rerun,
        "checkpoint_selection": {
            "rule": "first eligible non-terminal step >= ceil(last_eligible_step * fraction)",
            "fraction": checkpoint_fraction,
            "per_task": checkpoints,
        },
        "max_new_cost_usd_soft_cap": max_new_cost_usd,
        "aggregate": aggregate_reports(source_run, reports),
        "task_reports": reports,
    }


async def run_multitask_counterfactual(
    source_run: Path,
    out_dir: Path,
    tasks_root: Path,
    task_ids: list[str],
    candidates: dict[str, Path],
    *,
    checkpoint_fraction: float = 0.5,
    checkpoint_overrides: dict[str, int] | None = None,
    sandbox_kind: str = "docker",
    include_full_rerun: bool = False,
    resume: bool = False,
    max_new_cost_usd: float | None = None,
) -> dict[str, Any]:
    if not task_ids or len(task_ids) != len(set(task_ids)):
        raise ValueError("task ids must be a non-empty unique list")
    if not candidates:
        raise ValueError("provide at least one candidate harness")
    if any(not ARM_NAME.fullmatch(name) for name in candidates):
        raise ValueError("candidate names must match the counterfactual arm schema")
    if max_new_cost_usd is not None and max_new_cost_usd <= 0:
        raise ValueError("max new cost must be positive")

    source_run = Path(source_run)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "multitask_counterfactual_report.json"
    if report_path.exists() and not resume:
        raise FileExistsError(f"benchmark report already exists: {report_path}")
    if report_path.exists() and resume:
        existing = json.loads(report_path.read_text(encoding="utf-8"))
        if existing.get("status") == "completed":
            return existing

    checkpoint_overrides = checkpoint_overrides or {}
    unknown_overrides = set(checkpoint_overrides) - set(task_ids)
    if unknown_overrides:
        raise ValueError(f"checkpoint overrides reference unknown tasks: {unknown_overrides}")
    checkpoints = {
        task_id: (
            select_checkpoint(source_run, task_id, checkpoint_fraction)
            if task_id not in checkpoint_overrides
            else select_checkpoint(source_run, task_id, 1.0)
            | {"step": checkpoint_overrides[task_id], "selection_fraction": None}
        )
        for task_id in task_ids
    }
    # Validate explicit historical checkpoints and replace their accounting with
    # the requested record rather than the auto-selected terminal candidate.
    for task_id, step in checkpoint_overrides.items():
        record_path = (
            source_run / "checkpoint_history" / f"{task_id}-r0" / f"step-{step:04d}.json"
        )
        record = AgentCheckpointStore.read(record_path)
        if record.final_result is not None or not record.workspace_snapshot:
            raise ValueError(f"override {task_id} step {step} is not forkable")
        snapshot = source_run / "workspace_snapshots" / f"{task_id}-r0" / record.workspace_snapshot
        if not snapshot.exists():
            raise FileNotFoundError(f"override snapshot missing: {snapshot}")
        checkpoints[task_id] = {
            "step": step,
            "checkpoint": str(record_path.resolve()),
            "workspace_snapshot": record.workspace_snapshot,
            "prefix_tokens": record.tokens_in + record.tokens_out,
            "prefix_cost_usd": round(record.cost_usd, 6),
            "selection_fraction": None,
            "last_eligible_step": None,
        }

    reports: list[dict[str, Any]] = []
    for task_id in task_ids:
        task_report_path = out_dir / "tasks" / task_id / "counterfactual_report.json"
        if resume and task_report_path.exists():
            reports.append(json.loads(task_report_path.read_text(encoding="utf-8")))
            continue

        spent = aggregate_reports(source_run, reports).get("accounting", {}).get(
            "incremental_evaluation_cost_usd", 0.0
        )
        if max_new_cost_usd is not None and spent >= max_new_cost_usd:
            report = _batch_report(
                source_run, task_ids, candidates, checkpoints, reports,
                sandbox_kind=sandbox_kind,
                include_full_rerun=include_full_rerun,
                checkpoint_fraction=checkpoint_fraction,
                status="soft_cost_cap_reached",
                max_new_cost_usd=max_new_cost_usd,
            )
            _write_json_atomic(report_path, report)
            return report

        task_report = await run_counterfactual(
            source_run,
            out_dir / "tasks" / task_id,
            tasks_root,
            task_id,
            candidates,
            step=int(checkpoints[task_id]["step"]),
            sandbox_kind=sandbox_kind,
            include_full_rerun=include_full_rerun,
            resume=resume,
        )
        reports.append(task_report)
        progress = _batch_report(
            source_run, task_ids, candidates, checkpoints, reports,
            sandbox_kind=sandbox_kind,
            include_full_rerun=include_full_rerun,
            checkpoint_fraction=checkpoint_fraction,
            status="in_progress",
            max_new_cost_usd=max_new_cost_usd,
        )
        _write_json_atomic(report_path, progress)

    report = _batch_report(
        source_run, task_ids, candidates, checkpoints, reports,
        sandbox_kind=sandbox_kind,
        include_full_rerun=include_full_rerun,
        checkpoint_fraction=checkpoint_fraction,
        status="completed",
        max_new_cost_usd=max_new_cost_usd,
    )
    _write_json_atomic(report_path, report)
    return report


def _checkpoint_override(value: str) -> tuple[str, int]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("checkpoint must be TASK_ID=STEP")
    task_id, raw_step = value.split("=", 1)
    try:
        step = int(raw_step)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("checkpoint step must be an integer") from exc
    if step <= 0:
        raise argparse.ArgumentTypeError("checkpoint step must be positive")
    return task_id, step


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--tasks", type=Path, default=Path("tasks"))
    parser.add_argument("--task-ids", nargs="+", required=True)
    parser.add_argument("--candidate", type=_candidate, action="append", required=True,
                        metavar="NAME=HARNESS_DIR")
    parser.add_argument("--checkpoint-fraction", type=float, default=0.5)
    parser.add_argument("--checkpoint", type=_checkpoint_override, action="append",
                        default=[], metavar="TASK_ID=STEP")
    parser.add_argument("--sandbox", choices=["docker", "local"], default="docker")
    parser.add_argument("--include-full-rerun", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--max-new-cost-usd",
        type=float,
        help="soft cap checked between tasks; one in-flight task may overshoot it",
    )
    args = parser.parse_args()
    candidates = dict(args.candidate)
    if len(candidates) != len(args.candidate):
        parser.error("candidate names must be unique")
    overrides = dict(args.checkpoint)
    if len(overrides) != len(args.checkpoint):
        parser.error("checkpoint task ids must be unique")
    report = asyncio.run(run_multitask_counterfactual(
        args.source_run,
        args.out,
        args.tasks,
        args.task_ids,
        candidates,
        checkpoint_fraction=args.checkpoint_fraction,
        checkpoint_overrides=overrides,
        sandbox_kind=args.sandbox,
        include_full_rerun=args.include_full_rerun,
        resume=args.resume,
        max_new_cost_usd=args.max_new_cost_usd,
    ))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
