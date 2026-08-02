"""Validation gate: paired before/after comparison on a targeted task subset.

Design (noise-aware, budget-aware, revision-isolated):
- Validation set = tasks that failed under the targeted pattern + a small fixed
  regression set (tasks that currently pass).
- Run each validation task `repeats` times before AND after the change; compare
  per-task (paired), not aggregate pass rate.
- Accept iff: net improvement on targeted tasks > 0 AND no regression-set task
  flips from always-pass to ever-fail AND cost delta within budget.
- Every candidate is evaluated in its own materialized harness revision. Validation
  never mutates the live harness; the round driver promotes only the winning
  candidate in each group.
- Backfill observed_* fields on every proposal for the calibration table.

Usage:
    python -m harnessforge.selfharness.validation --proposals runs/round1/proposals.json \\
        --baseline runs/baseline --regression-tasks t01 t05 t09 --repeats 2
"""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from ..config import EVOLVABLE_COMPONENTS, HARNESS_DIR, HarnessConfig
from .proposal import apply_diff_to_text
from .schema import Proposal

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


def materialize_candidate(proposal: Proposal, base_harness_dir: Path,
                          candidate_harness_dir: Path) -> Path:
    """Create an isolated harness revision containing exactly one proposal.

    Candidate evaluation must be referentially transparent with respect to the
    live harness: all siblings branch from the same parent revision, and rejected
    or lower-ranked candidates leave no state behind.
    """
    candidate_harness_dir.mkdir(parents=True, exist_ok=True)
    for component in EVOLVABLE_COMPONENTS:
        shutil.copy2(Path(base_harness_dir) / component, candidate_harness_dir / component)

    target = candidate_harness_dir / proposal.component
    original = target.read_text(encoding="utf-8")
    patched = apply_diff_to_text(original, proposal.diff)
    if patched is None:
        raise RuntimeError(f"{proposal.proposal_id}: diff no longer applies")
    target.write_text(patched, encoding="utf-8")
    return candidate_harness_dir


def promote_proposal(proposal: Proposal, harness_dir: Path = HARNESS_DIR) -> Path:
    """Atomically promote one validated winner into the live harness revision.

    The previous component is archived first. The caller is responsible for only
    promoting the selected winner from a candidate group.
    """
    harness_dir = Path(harness_dir)
    target = harness_dir / proposal.component
    original = target.read_text(encoding="utf-8")
    patched = apply_diff_to_text(original, proposal.diff)
    if patched is None:
        raise RuntimeError(f"{proposal.proposal_id}: diff no longer applies to parent revision")

    history_dir = harness_dir / "_history"
    history_dir.mkdir(exist_ok=True)
    backup = history_dir / f"{time.time_ns()}-{proposal.proposal_id}-{proposal.component}"
    shutil.copy2(target, backup)
    pending = target.with_suffix(target.suffix + f".{proposal.proposal_id}.tmp")
    pending.write_text(patched, encoding="utf-8")
    os.replace(pending, target)
    return backup


async def validate(proposal: Proposal, baseline_dir: Path, regression_tasks: list[str],
                   tasks_root: Path, out_root: Path, repeats: int = 2,
                   sandbox_kind: str = "docker",
                   base_harness_dir: Path = HARNESS_DIR) -> ValidationVerdict:
    from ..eval.runner import run_suite

    targeted = targeted_tasks_for(proposal, baseline_dir)
    val_tasks = sorted(set(targeted) | set(regression_tasks))
    if not targeted:
        return ValidationVerdict(proposal.proposal_id, False, 0.0, 0, 0.0,
                                 "no targeted tasks found for pattern")

    # --- BEFORE: current harness on the validation set -------------------------
    before = await run_suite(
        tasks_root,
        out_root / f"{proposal.proposal_id}-before",
        repeats=repeats,
        task_ids=val_tasks,
        sandbox_kind=sandbox_kind,
        harness_dir=base_harness_dir,
    )

    # --- materialize an isolated candidate, AFTER, decide ----------------------
    candidate_harness_dir = materialize_candidate(
        proposal, base_harness_dir, out_root / f"{proposal.proposal_id}-harness"
    )
    after = await run_suite(
        tasks_root,
        out_root / f"{proposal.proposal_id}-after",
        repeats=repeats,
        task_ids=val_tasks,
        sandbox_kind=sandbox_kind,
        harness_dir=candidate_harness_dir,
    )

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

    # Round-1 lesson: with few repeats, small positive deltas are noise. Require
    # a substantial effect size before merging (see EXPERIMENTS.md, round 1).
    MIN_EFFECT = 0.25
    accepted = targeted_delta >= MIN_EFFECT and regression_flips == 0 and cost_delta_pct < 50

    # Backfill the calibration fields.
    proposal.observed_pass_rate_delta = round(targeted_delta, 3)
    proposal.observed_cost_delta_pct = round(cost_delta_pct, 1)
    proposal.accepted = accepted
    proposal.validation_notes = (
        f"targeted_delta={targeted_delta:+.3f} "
        f"(predicted {proposal.expected_pass_rate_delta:+.3f}), "
        f"regression_flips={regression_flips}, cost_delta={cost_delta_pct:+.1f}%"
    )

    candidate_version = HarnessConfig.load(candidate_harness_dir).version
    return ValidationVerdict(
        proposal_id=proposal.proposal_id, accepted=accepted,
        targeted_delta=round(targeted_delta, 3), regression_flips=regression_flips,
        cost_delta_pct=round(cost_delta_pct, 1),
        notes=f"candidate_version={candidate_version}; live harness unchanged",
    )
