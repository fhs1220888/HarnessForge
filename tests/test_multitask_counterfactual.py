"""Multi-task same-prefix benchmark selection and accounting."""

from __future__ import annotations

from pathlib import Path

from harnessforge.agent.checkpoint import (
    AgentCheckpoint,
    AgentCheckpointStore,
    prompt_fingerprint,
)
from harnessforge.eval.multitask_counterfactual import (
    aggregate_reports,
    select_checkpoint,
)


def _save_checkpoint(root: Path, task_id: str, step: int, *, completed: bool = False) -> None:
    run_key = f"{task_id}-r0"
    workspace = root / "workspaces" / run_key
    workspace.mkdir(parents=True, exist_ok=True)
    workspace.joinpath("state.txt").write_text(f"step={step}\n", encoding="utf-8")
    store = AgentCheckpointStore(
        root / "checkpoints" / f"{run_key}.json",
        workspace=workspace,
        snapshots_dir=root / "workspace_snapshots" / run_key,
        history_dir=root / "checkpoint_history" / run_key,
    )
    store.save(AgentCheckpoint(
        harness_version="test-harness",
        task_prompt_hash=prompt_fingerprint("task"),
        next_step=step,
        messages=[{"role": "user", "content": "task"}],
        tokens_in=step * 100,
        tokens_out=step * 10,
        cost_usd=step / 1000,
        final_result={"exit_reason": "finished_done"} if completed else None,
    ))


def _arm(
    *,
    name: str,
    fork_passed: bool,
    fork_tokens: int,
    fork_cost: float,
    prefix_tokens: int,
    prefix_cost: float,
    full_passed: bool,
    full_tokens: int,
    full_cost: float,
) -> dict:
    return {
        "name": name,
        "fork": {
            "passed": fork_passed,
            "steps": 4,
            "continuation_usage": {"tokens": fork_tokens, "cost_usd": fork_cost},
            "prefix_reused_tokens": prefix_tokens,
            "prefix_reused_cost_usd": prefix_cost,
        },
        "full_rerun": {
            "passed": full_passed,
            "usage": {"tokens": full_tokens, "cost_usd": full_cost},
        },
    }


def test_checkpoint_selection_uses_declared_midpoint_rule(tmp_path):
    for step in (1, 2, 3):
        _save_checkpoint(tmp_path, "task-a", step)
    _save_checkpoint(tmp_path, "task-a", 4, completed=True)

    selected = select_checkpoint(tmp_path, "task-a", fraction=0.5)

    assert selected["step"] == 2
    assert selected["last_eligible_step"] == 3
    assert selected["prefix_tokens"] == 220
    assert selected["workspace_snapshot"] == "step-0002"


def test_multitask_aggregate_separates_prefix_source_and_new_spend(tmp_path):
    reports = [
        {
            "task_id": "task-a",
            "arms": [_arm(
                name="baseline", fork_passed=True, fork_tokens=100, fork_cost=0.010,
                prefix_tokens=50, prefix_cost=0.005, full_passed=True,
                full_tokens=140, full_cost=0.014,
            )],
        },
        {
            "task_id": "task-b",
            "arms": [_arm(
                name="baseline", fork_passed=False, fork_tokens=120, fork_cost=0.012,
                prefix_tokens=60, prefix_cost=0.006, full_passed=True,
                full_tokens=160, full_cost=0.016,
            )],
        },
    ]

    aggregate = aggregate_reports(tmp_path, reports)

    assert aggregate["fork_outcomes"]["successes"] == 1
    assert aggregate["fork_outcomes"]["rate"] == 0.5
    assert aggregate["continuation_usage"] == {"tokens": 220, "cost_usd": 0.022}
    assert aggregate["reused_prefix"] == {"tokens": 110, "cost_usd": 0.011}
    control = aggregate["full_rerun_control"]
    assert control["outcomes"]["successes"] == 2
    assert control["outcome_agreement"]["rate"] == 0.5
    assert control["savings"]["tokens"] == 80
    assert control["savings"]["token_fraction"] == 0.266667
    assert control["savings"]["cost_usd"] == 0.008
    assert control["savings"]["paired_continuation_minus_full_tokens"]["n_tasks"] == 2
    assert aggregate["accounting"]["incremental_evaluation_cost_usd"] == 0.052
