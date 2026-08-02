"""Paired comparison for multi-task same-prefix candidate reports."""

from __future__ import annotations

import copy

import pytest

from harnessforge.eval.compare_counterfactual import compare_reports


def _report(name: str, outcomes: list[tuple[bool, int, float]]) -> dict:
    task_ids = [f"task-{index}" for index in range(len(outcomes))]
    return {
        "benchmark": "multitask-same-prefix-counterfactual",
        "status": "completed",
        "source_run": "/runs/shared-source",
        "task_ids_completed": task_ids,
        "candidates": {name: f"/harnesses/{name}"},
        "checkpoint_selection": {
            "per_task": {
                task_id: {"step": 4, "prefix_tokens": 1000, "prefix_cost_usd": 0.01}
                for task_id in task_ids
            }
        },
        "task_reports": [
            {
                "task_id": task_id,
                "arms": [{
                    "name": name,
                    "harness_version": f"{name}-version",
                    "fork": {
                        "passed": passed,
                        "exit_reason": "max_steps",
                        "steps": 8,
                        "continuation_usage": {
                            "tokens": tokens,
                            "cost_usd": cost,
                        },
                    },
                }],
            }
            for task_id, (passed, tokens, cost) in zip(task_ids, outcomes, strict=True)
        ],
    }


def test_compare_reports_pairs_quality_flips_and_efficiency():
    control = _report(
        "baseline",
        [(True, 100, 0.010), (True, 120, 0.012), (False, 140, 0.014)],
    )
    treatment = _report(
        "verify",
        [(True, 80, 0.008), (False, 90, 0.009), (True, 100, 0.010)],
    )

    report = compare_reports(control, treatment)

    assert report["control"]["outcomes"]["rate"] == pytest.approx(2 / 3)
    assert report["treatment"]["outcomes"]["rate"] == pytest.approx(2 / 3)
    paired = report["paired_analysis"]
    assert paired["mcnemar_exact"] == {
        "control_only_passes": 1,
        "treatment_only_passes": 1,
        "discordant_pairs": 2,
        "two_sided_p_value": 1.0,
    }
    assert paired["continuation_token_delta"]["ci_high"] < 0
    assert paired["continuation_cost_usd_delta"]["ci_high"] < 0
    assert report["verdict"]["classification"] == (
        "treatment_efficiency_gain_with_no_observed_quality_loss"
    )
    assert [row["outcome"]["flip"] for row in report["per_task"]] == [
        "both_pass", "control_only", "treatment_only"
    ]


def test_compare_reports_rejects_checkpoint_mismatch():
    control = _report("baseline", [(True, 100, 0.01)])
    treatment = _report("verify", [(True, 90, 0.009)])
    mismatched = copy.deepcopy(treatment)
    mismatched["checkpoint_selection"]["per_task"]["task-0"]["step"] = 5

    with pytest.raises(ValueError, match="checkpoint mismatch"):
        compare_reports(control, mismatched)
