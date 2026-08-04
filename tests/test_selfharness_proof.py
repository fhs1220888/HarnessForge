from __future__ import annotations

import json
from pathlib import Path

import pytest

from harnessforge.selfharness.proof import build_causal_proof


def _write_arm(
    path: Path,
    outcomes: dict[str, list[bool]],
    harness_version: str,
    *,
    model: str = "model-a",
) -> None:
    path.mkdir()
    tasks = sorted(outcomes)
    repeats = len(next(iter(outcomes.values())))
    manifest = {
        "benchmark": "terminal-bench-2 / causal-holdout",
        "harness_version": harness_version,
        "agent_model": model,
        "provider": "anthropic",
        "task_ids": tasks,
        "repeats": repeats,
        "max_steps": 40,
        "temperature": 0,
        "max_output_tokens": 16384,
        "suite_content_hash": "tasks-v1",
        "extra": {
            "terminal_bench_revision": "tb-rev",
            "max_cost_usd_per_task": 2.0,
            "max_output_tokens_per_call": 16384,
            "declared_docker_images": {task: f"image:{task}" for task in tasks},
        },
    }
    (path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    rows = []
    for task, values in outcomes.items():
        for repeat, passed in enumerate(values):
            rows.append(
                {
                    "task_id": task,
                    "repeat": repeat,
                    "run_id": f"{harness_version}-{task}-{repeat}",
                    "passed": passed,
                    "exit_reason": "finished_done",
                    "steps": 10 if passed else 20,
                    "cost_usd": 0.5,
                    "harness_version": harness_version,
                }
            )
    (path / "results.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )


def test_causal_proof_confirms_only_matched_sufficient_positive_experiment(tmp_path):
    tasks = [f"task-{index:02d}" for index in range(20)]
    control = {task: [False, False] for task in tasks}
    treatment = {task: [True, True] for task in tasks}
    _write_arm(tmp_path / "control", control, "round0")
    _write_arm(tmp_path / "treatment", treatment, "round3")

    proof = build_causal_proof(
        [tmp_path / "control"], [tmp_path / "treatment"]
    )

    assert proof["protocol_match"] is True
    assert proof["sample_requirements"]["met"] is True
    assert proof["paired_effects"]["pass_rate"]["ci_low"] > 0
    assert proof["decision"]["confirmed_causal_pass_rate_uplift"] is True


def test_causal_proof_keeps_positive_point_estimate_unconfirmed_when_underpowered(
    tmp_path,
):
    tasks = ["a", "b"]
    _write_arm(tmp_path / "control", {task: [False] for task in tasks}, "round0")
    _write_arm(tmp_path / "treatment", {task: [True] for task in tasks}, "round3")

    proof = build_causal_proof(
        [tmp_path / "control"], [tmp_path / "treatment"]
    )

    assert proof["paired_effects"]["pass_rate"]["mean_delta"] == 1.0
    assert proof["sample_requirements"]["met"] is False
    assert proof["decision"]["confirmed_causal_pass_rate_uplift"] is False


def test_causal_proof_rejects_model_or_task_content_mismatch(tmp_path):
    outcomes = {"a": [False, False], "b": [True, True]}
    _write_arm(tmp_path / "control", outcomes, "round0")
    _write_arm(tmp_path / "treatment", outcomes, "round3", model="model-b")

    with pytest.raises(ValueError, match="evaluation_protocol_equal"):
        build_causal_proof(
            [tmp_path / "control"], [tmp_path / "treatment"],
            minimum_tasks=2,
        )
