import json
from pathlib import Path

import pytest

from harnessforge.eval.holdout_scorecard import aggregate_holdout
from harnessforge.eval.stats import wilson_interval

REPO = Path(__file__).parents[1]


def _write_run(path: Path, tasks: list[str], outcomes: list[bool], suffix: str) -> None:
    path.mkdir()
    manifest = {
        "agent_model": "model-a",
        "max_steps": 40,
        "temperature": None,
        "extra": {
            "max_cost_usd_per_task": 2.0,
            "max_output_tokens_per_call": 16384,
            "terminal_bench_revision": "tb-rev",
        },
    }
    (path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    rows = [
        {
            "task_id": task,
            "repeat": 0,
            "run_id": f"{task}-{suffix}",
            "passed": passed,
            "exit_reason": "finished_done",
            "steps": 10,
            "cost_usd": 0.5,
            "tokens": 1000,
            "harness_version": "harness-a",
            "difficulty": "medium",
            "category": "test",
        }
        for task, passed in zip(tasks, outcomes, strict=True)
    ]
    (path / "results.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )


def test_aggregate_holdout_validates_and_summarizes_repeats(tmp_path):
    tasks = ["a", "b"]
    _write_run(tmp_path / "r1", tasks, [True, False], "r1")
    _write_run(tmp_path / "r2", tasks, [True, True], "r2")

    score = aggregate_holdout(
        [tmp_path / "r1", tmp_path / "r2"],
        expected_tasks=tasks,
        expected_repeats=2,
    )

    assert score["passed_runs"] == 3
    assert score["pass_rate"] == 0.75
    assert score["stability"] == {
        "stable_pass_2_of_2": 1,
        "mixed_1_of_2": 1,
        "stable_fail_0_of_2": 0,
    }
    assert score["total_cost_usd"] == 2.0
    assert score["protocol"]["max_tokens_per_call"] == 16384


def test_aggregate_holdout_refuses_incomplete_or_mixed_protocol(tmp_path):
    tasks = ["a", "b"]
    _write_run(tmp_path / "r1", tasks, [True, False], "r1")
    _write_run(tmp_path / "r2", ["a"], [True], "r2")
    with pytest.raises(ValueError, match="expected 2 outcomes"):
        aggregate_holdout(
            [tmp_path / "r1", tmp_path / "r2"],
            expected_tasks=tasks,
            expected_repeats=2,
        )

    _write_run(tmp_path / "r3", tasks, [True, True], "r3")
    manifest = json.loads((tmp_path / "r3" / "manifest.json").read_text())
    manifest["max_steps"] = 99
    (tmp_path / "r3" / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="mixed step budgets"):
        aggregate_holdout(
            [tmp_path / "r1", tmp_path / "r3"],
            expected_tasks=tasks,
            expected_repeats=2,
        )


def test_published_holdout_scorecard_has_consistent_denominators():
    score = json.loads(
        (REPO / "docs/data/tb_holdout_v1_verifier_scorecard.json").read_text()
    )
    outcomes = [value for values in score["per_task"].values() for value in values]
    passed = sum(outcomes)
    assert len(score["per_task"]) == score["task_count"] == 8
    assert all(len(values) == score["repeats_per_task"] == 2
               for values in score["per_task"].values())
    assert len(outcomes) == score["scored_runs"] == 16
    assert passed == score["passed_runs"] == 11
    assert score["pass_rate"] == passed / len(outcomes)
    assert score["infra_errors"] == 0
    expected_ci = [round(value, 4) for value in wilson_interval(passed, len(outcomes))]
    assert score["wilson_95"] == expected_ci
