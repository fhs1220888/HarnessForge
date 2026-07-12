"""Task selection for high-signal, budget-efficient validation.

Two levers against the "can't measure small real gains" problem (see
EXPERIMENTS.md, round 1):

1. Spend eval budget where a harness change can actually move the needle.
   Classify tasks from a baseline run into always_pass / always_fail / borderline;
   the informative set is borderline ∪ harness-fixable failures, plus a few
   always_pass tasks as regression guards.

2. Separate harness-fixable failures from capability-limited ones. A task where the
   agent hit the step budget while making progress is a harness problem (budget /
   completion). A task that needs a capability the model lacks in-budget (heavy ML
   training, etc.) will not be fixed by any prompt or policy change, so validating
   on it only adds noise.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TaskClass:
    always_pass: list[str] = field(default_factory=list)
    always_fail: list[str] = field(default_factory=list)
    borderline: list[str] = field(default_factory=list)  # 0 < pass rate < 1


def classify(results_path: Path) -> TaskClass:
    """Group tasks by observed pass rate in a results.jsonl (excluding infra errors)."""
    by_task: dict[str, list[bool]] = {}
    with Path(results_path).open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("exit_reason") in ("infra_error", "api_error"):
                continue
            by_task.setdefault(r["task_id"], []).append(bool(r["passed"]))

    tc = TaskClass()
    for task, results in by_task.items():
        rate = sum(results) / len(results)
        if rate == 1.0:
            tc.always_pass.append(task)
        elif rate == 0.0:
            tc.always_fail.append(task)
        else:
            tc.borderline.append(task)
    for lst in (tc.always_pass, tc.always_fail, tc.borderline):
        lst.sort()
    return tc


# Hand-classified from the tb_baseline run: which 0/2 failures are plausibly
# fixable by the harness (task is doable in-budget; the agent mismanaged its
# steps or never recognized completion) vs. capability-limited (needs heavy
# ML/compute the model can't deliver in the step budget regardless of harness).
TB_HARNESS_FIXABLE = [
    "prove-plus-comm",
    "crack-7z-hash",
    "openssl-selfsigned-cert",
    "polyglot-c-py",
    "merge-diff-arc-agi-task",
    "qemu-startup",
]
TB_CAPABILITY_LIMITED = [
    "mteb-leaderboard",
    "mteb-retrieve",
    "hf-model-inference",
    "raman-fitting",
]


def high_signal_set(baseline_results: Path, n_regression_guards: int = 3,
                    harness_fixable: list[str] | None = None) -> dict[str, list[str]]:
    """Build a validation set focused where a harness change can show signal.

    Returns {"targets": [...], "regression_guards": [...], "all": [...]}.
    Targets = borderline tasks + harness-fixable failures (drop capability-limited).
    Regression guards = a few always_pass tasks to catch collateral damage.
    """
    fixable = set(harness_fixable if harness_fixable is not None else TB_HARNESS_FIXABLE)
    tc = classify(baseline_results)

    targets = sorted(set(tc.borderline) | (set(tc.always_fail) & fixable))
    guards = tc.always_pass[:n_regression_guards]
    return {
        "targets": targets,
        "regression_guards": guards,
        "all": sorted(set(targets) | set(guards)),
    }
