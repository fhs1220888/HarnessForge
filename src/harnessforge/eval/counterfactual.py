"""Run same-prefix counterfactual experiments over candidate harness revisions.

Each candidate forks from the same committed checkpoint and workspace snapshot.
The report distinguishes:

- logical total usage: prefix + continuation, used for the agent's budget;
- incremental usage: only model calls made after the fork, i.e. actual new spend.

An optional full-rerun arm measures the savings directly, but is off by default
because it intentionally doubles evaluation work and API cost.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..config import HarnessConfig
from ..trace import load_trace
from .fork import ForkResult, fork_native_run
from .runner import run_suite

ARM_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


@dataclass(frozen=True)
class Usage:
    tokens_in: int
    tokens_out: int
    cost_usd: float

    @property
    def tokens(self) -> int:
        return self.tokens_in + self.tokens_out


def _trace_usage(trace_path: Path) -> Usage:
    events = load_trace(trace_path)
    return Usage(
        tokens_in=sum(
            int(event.get("tokens_in", 0))
            for event in events if event["event_type"] == "llm_response"
        ),
        tokens_out=sum(
            int(event.get("tokens_out", 0))
            for event in events if event["event_type"] == "llm_response"
        ),
        cost_usd=round(sum(
            float(event.get("cost_usd", 0.0))
            for event in events if event["event_type"] == "llm_response"
        ), 6),
    )


def _result_row(run_dir: Path) -> dict[str, Any]:
    rows = [
        json.loads(line)
        for line in (run_dir / "results.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(rows) != 1:
        raise RuntimeError(f"expected exactly one result in {run_dir}, found {len(rows)}")
    return rows[0]


async def run_counterfactual(
    source_run: Path,
    out_dir: Path,
    tasks_root: Path,
    task_id: str,
    candidates: dict[str, Path],
    *,
    step: int | None = None,
    sandbox_kind: str = "docker",
    include_full_rerun: bool = False,
) -> dict[str, Any]:
    if not candidates:
        raise ValueError("provide at least one candidate harness")
    invalid = [name for name in candidates if not ARM_NAME.fullmatch(name)]
    if invalid:
        raise ValueError(f"invalid candidate arm name(s): {invalid}")

    source_run = Path(source_run)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "counterfactual_report.json"
    if report_path.exists():
        raise FileExistsError(f"experiment report already exists: {report_path}")

    arms = []
    actual_checkpoint_step = None
    for name, harness_dir in candidates.items():
        harness_dir = Path(harness_dir)
        fork_dir = out_dir / f"{name}-fork"
        fork: ForkResult = fork_native_run(
            source_run, fork_dir, task_id, harness_dir, repeat=0, step=step
        )
        if actual_checkpoint_step is None:
            actual_checkpoint_step = fork.checkpoint_step
        await run_suite(
            tasks_root,
            fork_dir,
            repeats=1,
            concurrency=1,
            task_ids=[task_id],
            sandbox_kind=sandbox_kind,
            harness_dir=harness_dir,
            resume=True,
        )
        fork_row = _result_row(fork_dir)
        fork_usage = _trace_usage(fork_dir / "traces" / f"{task_id}-r0.jsonl")

        full_row = None
        full_usage = None
        if include_full_rerun:
            full_dir = out_dir / f"{name}-full"
            await run_suite(
                tasks_root,
                full_dir,
                repeats=1,
                concurrency=1,
                task_ids=[task_id],
                sandbox_kind=sandbox_kind,
                harness_dir=harness_dir,
                resume=False,
            )
            full_row = _result_row(full_dir)
            full_usage = _trace_usage(full_dir / "traces" / f"{task_id}-r0.jsonl")

        arms.append({
            "name": name,
            "harness_dir": str(harness_dir),
            "harness_version": HarnessConfig.load(harness_dir).version,
            "fork": {
                "passed": fork_row["passed"],
                "exit_reason": fork_row["exit_reason"],
                "steps": fork_row["steps"],
                "logical_total_tokens": fork_row["tokens"],
                "logical_total_cost_usd": fork_row["cost_usd"],
                "continuation_usage": asdict(fork_usage) | {"tokens": fork_usage.tokens},
                "prefix_reused_tokens": fork.prefix_tokens,
                "prefix_reused_cost_usd": fork.prefix_cost_usd,
            },
            "full_rerun": (
                {
                    "passed": full_row["passed"],
                    "exit_reason": full_row["exit_reason"],
                    "steps": full_row["steps"],
                    "usage": asdict(full_usage) | {"tokens": full_usage.tokens},
                }
                if full_row is not None and full_usage is not None else None
            ),
        })

    total_continuation_tokens = sum(
        arm["fork"]["continuation_usage"]["tokens"] for arm in arms
    )
    total_continuation_cost = sum(
        arm["fork"]["continuation_usage"]["cost_usd"] for arm in arms
    )
    total_prefix_tokens = sum(arm["fork"]["prefix_reused_tokens"] for arm in arms)
    total_prefix_cost = sum(arm["fork"]["prefix_reused_cost_usd"] for arm in arms)

    aggregate: dict[str, Any] = {
        "n_candidates": len(arms),
        "fork_passes": sum(bool(arm["fork"]["passed"]) for arm in arms),
        "actual_continuation_tokens": total_continuation_tokens,
        "actual_continuation_cost_usd": round(total_continuation_cost, 6),
        "reused_prefix_tokens": total_prefix_tokens,
        "reused_prefix_cost_usd": round(total_prefix_cost, 6),
        "candidate_ranking": [
            arm["name"]
            for arm in sorted(
                arms,
                key=lambda arm: (
                    not arm["fork"]["passed"],
                    arm["fork"]["continuation_usage"]["cost_usd"],
                    arm["fork"]["steps"],
                ),
            )
        ],
    }
    if include_full_rerun:
        full_tokens = sum(arm["full_rerun"]["usage"]["tokens"] for arm in arms)
        full_cost = sum(arm["full_rerun"]["usage"]["cost_usd"] for arm in arms)
        agreement_count = sum(
            arm["fork"]["passed"] == arm["full_rerun"]["passed"] for arm in arms
        )
        aggregate |= {
            "full_rerun_tokens": full_tokens,
            "full_rerun_cost_usd": round(full_cost, 6),
            "token_savings_vs_full": full_tokens - total_continuation_tokens,
            "token_savings_fraction": round(
                (full_tokens - total_continuation_tokens) / full_tokens, 6
            ) if full_tokens else None,
            "cost_savings_usd_vs_full": round(full_cost - total_continuation_cost, 6),
            "cost_savings_fraction": round(
                (full_cost - total_continuation_cost) / full_cost, 6
            ) if full_cost else None,
            # Keep the original count for report-schema compatibility, while
            # exposing explicit count/rate fields so "1" cannot be mistaken
            # for 100% agreement in a multi-candidate experiment.
            "outcome_agreement": agreement_count,
            "outcome_agreement_count": agreement_count,
            "outcome_agreement_rate": round(agreement_count / len(arms), 6),
        }

    report = {
        "source_run": str(source_run.resolve()),
        "task_id": task_id,
        "checkpoint_step": actual_checkpoint_step,
        "sandbox": sandbox_kind,
        "include_full_rerun": include_full_rerun,
        "arms": arms,
        "aggregate": aggregate,
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def _candidate(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("candidate must be NAME=HARNESS_DIR")
    name, path = value.split("=", 1)
    if not ARM_NAME.fullmatch(name):
        raise argparse.ArgumentTypeError(f"invalid candidate name: {name!r}")
    return name, Path(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--tasks", type=Path, default=Path("tasks"))
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--step", type=int)
    parser.add_argument("--candidate", type=_candidate, action="append", required=True,
                        metavar="NAME=HARNESS_DIR")
    parser.add_argument("--sandbox", choices=["docker", "local"], default="docker")
    parser.add_argument(
        "--include-full-rerun",
        action="store_true",
        help="also run every candidate from scratch (extra model/API cost)",
    )
    args = parser.parse_args()
    candidates = dict(args.candidate)
    if len(candidates) != len(args.candidate):
        parser.error("candidate names must be unique")
    report = asyncio.run(run_counterfactual(
        args.source_run,
        args.out,
        args.tasks,
        args.task_id,
        candidates,
        step=args.step,
        sandbox_kind=args.sandbox,
        include_full_rerun=args.include_full_rerun,
    ))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
