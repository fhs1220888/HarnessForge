"""Compare two multi-task same-prefix candidate reports.

The comparator refuses pseudo-pairs: both inputs must come from the same source
run and use the same task/checkpoint/prefix ledger. Binary quality is reported
with paired bootstrap and an exact McNemar test; continuous efficiency metrics use
the existing paired task bootstrap.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from .counterfactual import _write_json_atomic
from .stats import (
    paired_bootstrap_continuous,
    paired_bootstrap_delta,
    wilson_interval,
)


def _load_report(path: Path) -> dict[str, Any]:
    report = json.loads(Path(path).read_text(encoding="utf-8"))
    if report.get("benchmark") != "multitask-same-prefix-counterfactual":
        raise ValueError(f"not a multi-task counterfactual report: {path}")
    if report.get("status") != "completed":
        raise ValueError(f"counterfactual report is not completed: {path}")
    return report


def _choose_arm(report: dict[str, Any], requested: str | None, label: str) -> str:
    available = sorted(report.get("candidates", {}))
    if requested is not None:
        if requested not in available:
            raise ValueError(f"{label} arm {requested!r} not in {available}")
        return requested
    if len(available) != 1:
        raise ValueError(f"choose --{label}-arm from {available}")
    return available[0]


def _task_arms(report: dict[str, Any], arm_name: str) -> dict[str, dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    for task_report in report["task_reports"]:
        matches = [arm for arm in task_report["arms"] if arm["name"] == arm_name]
        if len(matches) != 1:
            raise ValueError(
                f"expected one {arm_name!r} arm for {task_report['task_id']}, "
                f"found {len(matches)}"
            )
        selected[task_report["task_id"]] = matches[0]
    return selected


def _harness_version(arms: dict[str, dict[str, Any]]) -> str:
    versions = {arm["harness_version"] for arm in arms.values()}
    if len(versions) != 1:
        raise ValueError(f"candidate report contains mixed harness versions: {versions}")
    return versions.pop()


def _validate_pair(control: dict[str, Any], treatment: dict[str, Any]) -> list[str]:
    if control["source_run"] != treatment["source_run"]:
        raise ValueError("reports use different source runs")
    control_tasks = control["task_ids_completed"]
    treatment_tasks = treatment["task_ids_completed"]
    if control_tasks != treatment_tasks:
        raise ValueError("reports use different ordered task sets")

    control_points = control["checkpoint_selection"]["per_task"]
    treatment_points = treatment["checkpoint_selection"]["per_task"]
    for task_id in control_tasks:
        left = control_points[task_id]
        right = treatment_points[task_id]
        for field in ("step", "prefix_tokens", "prefix_cost_usd"):
            if left[field] != right[field]:
                raise ValueError(
                    f"checkpoint mismatch for {task_id} field {field}: "
                    f"{left[field]} != {right[field]}"
                )
    return control_tasks


def _rate(successes: int, observations: int) -> dict[str, Any]:
    low, high = wilson_interval(successes, observations)
    return {
        "successes": successes,
        "observations": observations,
        "rate": round(successes / observations, 6) if observations else None,
        "wilson_ci95": [round(low, 6), round(high, 6)] if observations else None,
    }


def _mcnemar_exact(control_only: int, treatment_only: int) -> dict[str, Any]:
    discordant = control_only + treatment_only
    if discordant == 0:
        p_value = 1.0
    else:
        tail = sum(
            math.comb(discordant, k) for k in range(min(control_only, treatment_only) + 1)
        ) / (2 ** discordant)
        p_value = min(1.0, 2 * tail)
    return {
        "control_only_passes": control_only,
        "treatment_only_passes": treatment_only,
        "discordant_pairs": discordant,
        "two_sided_p_value": round(p_value, 6),
    }


def _continuous(
    task_ids: list[str],
    control_arms: dict[str, dict[str, Any]],
    treatment_arms: dict[str, dict[str, Any]],
    getter,
) -> dict[str, Any]:
    before = {task_id: [float(getter(control_arms[task_id]))] for task_id in task_ids}
    after = {task_id: [float(getter(treatment_arms[task_id]))] for task_id in task_ids}
    return paired_bootstrap_continuous(before, after, seed=20260803)


def compare_reports(
    control: dict[str, Any],
    treatment: dict[str, Any],
    *,
    control_arm: str | None = None,
    treatment_arm: str | None = None,
) -> dict[str, Any]:
    task_ids = _validate_pair(control, treatment)
    control_name = _choose_arm(control, control_arm, "control")
    treatment_name = _choose_arm(treatment, treatment_arm, "treatment")
    control_arms = _task_arms(control, control_name)
    treatment_arms = _task_arms(treatment, treatment_name)

    rows = []
    control_passes = 0
    treatment_passes = 0
    control_only = 0
    treatment_only = 0
    for task_id in task_ids:
        left = control_arms[task_id]["fork"]
        right = treatment_arms[task_id]["fork"]
        left_passed = bool(left["passed"])
        right_passed = bool(right["passed"])
        control_passes += left_passed
        treatment_passes += right_passed
        control_only += left_passed and not right_passed
        treatment_only += right_passed and not left_passed
        if left_passed == right_passed:
            flip = "both_pass" if left_passed else "both_fail"
        else:
            flip = "control_only" if left_passed else "treatment_only"
        rows.append({
            "task_id": task_id,
            "outcome": {
                "control_passed": left_passed,
                "treatment_passed": right_passed,
                "flip": flip,
            },
            "control": {
                "exit_reason": left["exit_reason"],
                "steps": left["steps"],
                "continuation_tokens": left["continuation_usage"]["tokens"],
                "continuation_cost_usd": left["continuation_usage"]["cost_usd"],
            },
            "treatment": {
                "exit_reason": right["exit_reason"],
                "steps": right["steps"],
                "continuation_tokens": right["continuation_usage"]["tokens"],
                "continuation_cost_usd": right["continuation_usage"]["cost_usd"],
            },
        })

    before_pass = {task_id: [control_arms[task_id]["fork"]["passed"]]
                   for task_id in task_ids}
    after_pass = {task_id: [treatment_arms[task_id]["fork"]["passed"]]
                  for task_id in task_ids}
    pass_delta = paired_bootstrap_delta(before_pass, after_pass, seed=20260803)
    token_delta = _continuous(
        task_ids, control_arms, treatment_arms,
        lambda arm: arm["fork"]["continuation_usage"]["tokens"],
    )
    cost_delta = _continuous(
        task_ids, control_arms, treatment_arms,
        lambda arm: arm["fork"]["continuation_usage"]["cost_usd"],
    )
    step_delta = _continuous(
        task_ids, control_arms, treatment_arms,
        lambda arm: arm["fork"]["steps"],
    )

    quality_confirmed = (
        pass_delta["ci_low"] > 0
        and _mcnemar_exact(control_only, treatment_only)["two_sided_p_value"] < 0.05
    )
    efficiency_confirmed = any(
        metric["ci_high"] < 0 for metric in (token_delta, cost_delta, step_delta)
    )
    if quality_confirmed:
        verdict = "treatment_quality_gain_confirmed"
    elif treatment_passes < control_passes:
        verdict = "treatment_regressed_on_observed_tasks"
    elif efficiency_confirmed and treatment_passes >= control_passes:
        verdict = "treatment_efficiency_gain_with_no_observed_quality_loss"
    else:
        verdict = "underpowered_or_no_confirmed_gain"

    return {
        "schema_version": 1,
        "comparison": "paired-same-prefix-harness-candidates",
        "source_run_id": Path(control["source_run"]).name,
        "task_ids": task_ids,
        "control": {
            "arm": control_name,
            "harness_dir": Path(control["candidates"][control_name]).name,
            "harness_version": _harness_version(control_arms),
            "outcomes": _rate(control_passes, len(task_ids)),
        },
        "treatment": {
            "arm": treatment_name,
            "harness_dir": Path(treatment["candidates"][treatment_name]).name,
            "harness_version": _harness_version(treatment_arms),
            "outcomes": _rate(treatment_passes, len(task_ids)),
        },
        "paired_analysis": {
            "pass_rate_delta": pass_delta,
            "mcnemar_exact": _mcnemar_exact(control_only, treatment_only),
            "continuation_token_delta": token_delta,
            "continuation_cost_usd_delta": cost_delta,
            "step_delta": step_delta,
        },
        "verdict": {
            "classification": verdict,
            "quality_gain_confirmed": quality_confirmed,
            "efficiency_gain_confirmed": efficiency_confirmed,
            "note": (
                "One continuation per task controls the prefix but remains a small "
                "stochastic sample; non-confirmation is not evidence of equivalence."
            ),
        },
        "per_task": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--control", type=Path, required=True)
    parser.add_argument("--treatment", type=Path, required=True)
    parser.add_argument("--control-arm")
    parser.add_argument("--treatment-arm")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    report = compare_reports(
        _load_report(args.control),
        _load_report(args.treatment),
        control_arm=args.control_arm,
        treatment_arm=args.treatment_arm,
    )
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        _write_json_atomic(args.out, report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
