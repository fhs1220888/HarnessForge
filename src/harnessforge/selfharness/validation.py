"""Validation gate: paired before/after comparison on a targeted task subset.

Design (noise-aware, budget-aware):
- Validation set = tasks that failed under the targeted pattern + a small fixed
  regression set (tasks that currently pass).
- Run each validation task `repeats` times before AND after the change; compare
  per-task (paired), not aggregate pass rate.
- Accept iff: net improvement on targeted tasks > 0 AND no regression-set task
  flips from always-pass to ever-fail AND cost delta within budget.
- On accept: apply diff to harness/, archive the old version to harness/_history/,
  backfill observed_* fields on the proposal (calibration table).
- On reject: revert workspace, record why.

Usage:
    python -m harnessforge.selfharness.validation --proposals runs/round1/proposals.json \\
        --baseline runs/baseline --regression-tasks t01 t05 t09 --repeats 2
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from ..config import HARNESS_DIR, HarnessConfig
from .proposal import apply_diff_to_text
from .schema import Proposal

HISTORY_DIR = HARNESS_DIR / "_history"


@dataclass
class ValidationVerdict:
    proposal_id: str
    accepted: bool
    targeted_delta: float        # per-task paired pass-rate delta on targeted tasks
    regression_flips: int        # regression tasks that flipped pass -> fail
    cost_delta_pct: float
    notes: str = ""


def targeted_tasks_for(proposal: Proposal, baseline_dir: Path) -> list[str]:
    """Tasks whose failed runs are evidence for the proposal's failure pattern."""
    report_path = baseline_dir / "mining_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    evidence_runs: set[str] = set()
    for p in report["patterns"]:
        if p["pattern_id"] == proposal.failure_pattern:
            evidence_runs.update(p["evidence_runs"])
    task_ids: set[str] = set()
    with (baseline_dir / "results.jsonl").open(encoding="utf-8") as f:
        for line in f:
            o = json.loads(line)
            if o["run_id"] in evidence_runs:
                task_ids.add(o["task_id"])
    return sorted(task_ids)


def _apply_to_harness(proposal: Proposal) -> Path:
    """Apply the diff to harness/<component>, archiving the previous version."""
    target = HARNESS_DIR / proposal.component
    original = target.read_text(encoding="utf-8")
    patched = apply_diff_to_text(original, proposal.diff)
    if patched is None:
        raise RuntimeError(f"{proposal.proposal_id}: diff no longer applies")
    HISTORY_DIR.mkdir(exist_ok=True)
    backup = HISTORY_DIR / f"{int(time.time())}-{proposal.proposal_id}-{proposal.component}"
    shutil.copy(target, backup)
    target.write_text(patched, encoding="utf-8")
    return backup


def _revert(backup: Path, component: str) -> None:
    shutil.copy(backup, HARNESS_DIR / component)


async def validate(proposal: Proposal, baseline_dir: Path, regression_tasks: list[str],
                   tasks_root: Path, out_root: Path, repeats: int = 2,
                   sandbox_kind: str = "docker") -> ValidationVerdict:
    from ..eval.runner import run_suite

    targeted = targeted_tasks_for(proposal, baseline_dir)
    val_tasks = sorted(set(targeted) | set(regression_tasks))
    if not targeted:
        return ValidationVerdict(proposal.proposal_id, False, 0.0, 0, 0.0,
                                 "no targeted tasks found for pattern")

    # --- BEFORE: current harness on the validation set -------------------------
    before = await run_suite(tasks_root, out_root / f"{proposal.proposal_id}-before",
                             repeats=repeats, task_ids=val_tasks, sandbox_kind=sandbox_kind)

    # --- apply, AFTER, decide ---------------------------------------------------
    backup = _apply_to_harness(proposal)
    try:
        after = await run_suite(tasks_root, out_root / f"{proposal.proposal_id}-after",
                                repeats=repeats, task_ids=val_tasks, sandbox_kind=sandbox_kind)
    except Exception:
        _revert(backup, proposal.component)
        raise

    def per_task_rate(summary: dict, task_id: str) -> float:
        results = summary["per_task"].get(task_id, [])
        return sum(results) / len(results) if results else 0.0

    targeted_delta = sum(
        per_task_rate(after, t) - per_task_rate(before, t) for t in targeted
    ) / len(targeted)
    regression_flips = sum(
        1 for t in regression_tasks
        if per_task_rate(before, t) == 1.0 and per_task_rate(after, t) < 1.0
    )
    cost_before = max(before["total_cost_usd"], 1e-9)
    cost_delta_pct = (after["total_cost_usd"] - before["total_cost_usd"]) / cost_before * 100

    accepted = targeted_delta > 0 and regression_flips == 0 and cost_delta_pct < 50
    if not accepted:
        _revert(backup, proposal.component)

    # Backfill the calibration fields.
    proposal.observed_pass_rate_delta = round(targeted_delta, 3)
    proposal.observed_cost_delta_pct = round(cost_delta_pct, 1)
    proposal.accepted = accepted
    proposal.validation_notes = (
        f"targeted_delta={targeted_delta:+.3f} "
        f"(predicted {proposal.expected_pass_rate_delta:+.3f}), "
        f"regression_flips={regression_flips}, cost_delta={cost_delta_pct:+.1f}%"
    )

    new_version = HarnessConfig.load().version
    return ValidationVerdict(
        proposal_id=proposal.proposal_id, accepted=accepted,
        targeted_delta=round(targeted_delta, 3), regression_flips=regression_flips,
        cost_delta_pct=round(cost_delta_pct, 1),
        notes=f"harness_version now {new_version}" if accepted else "reverted",
    )
