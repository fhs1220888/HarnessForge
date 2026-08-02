"""Counterfactual native-run fork from a historical checkpoint."""

from __future__ import annotations

from pathlib import Path

import pytest

from harnessforge.agent.checkpoint import AgentCheckpointStore
from harnessforge.agent.llm import LLMResponse
from harnessforge.config import HarnessConfig
from harnessforge.eval import runner as runner_mod
from harnessforge.eval.counterfactual import run_counterfactual
from harnessforge.eval.fork import fork_native_run
from harnessforge.eval.task import Task
from harnessforge.trace import load_trace

REPO = Path(__file__).parents[1]
FIXED_CALC = '''def sum_range(a: int, b: int) -> int:
    """Sum integers from a to b inclusive."""
    return sum(range(a, b + 1))
'''


class WriteThenCrash:
    model = "write-then-crash"

    def __init__(self):
        self.calls = 0

    async def complete(self, *_args, **_kwargs):
        self.calls += 1
        if self.calls == 2:
            raise RuntimeError("fork fixture crash")
        call = {
            "id": "write",
            "name": "write_file",
            "input": {"path": "calc.py", "content": FIXED_CALC},
        }
        return LLMResponse(
            text="", tool_calls=[call], stop_reason="tool_use",
            tokens_in=100, tokens_out=50, cost_usd=0.001,
            raw_content=[{"type": "tool_use", **call}],
        )


class VerifyAndFinish:
    model = "verify-and-finish"

    def __init__(self):
        self.calls = 0

    async def complete(self, *_args, **_kwargs):
        self.calls += 1
        if self.calls == 1:
            call = {
                "id": "test",
                "name": "bash",
                "input": {"command": "python -m pytest tests/ -q"},
            }
        else:
            call = {
                "id": "finish",
                "name": "finish",
                "input": {"status": "done", "summary": "fork verified"},
            }
        return LLMResponse(
            text="", tool_calls=[call], stop_reason="tool_use",
            tokens_in=100, tokens_out=50, cost_usd=0.001,
            raw_content=[{"type": "tool_use", **call}],
        )


class FullSolve:
    model = "full-solve"

    def __init__(self):
        self.calls = 0

    async def complete(self, *_args, **_kwargs):
        self.calls += 1
        if self.calls == 1:
            call = {
                "id": "write-full",
                "name": "write_file",
                "input": {"path": "calc.py", "content": FIXED_CALC},
            }
        elif self.calls == 2:
            call = {
                "id": "test-full",
                "name": "bash",
                "input": {"command": "python -m pytest tests/ -q"},
            }
        else:
            call = {
                "id": "finish-full",
                "name": "finish",
                "input": {"status": "done", "summary": "full run verified"},
            }
        return LLMResponse(
            text="", tool_calls=[call], stop_reason="tool_use",
            tokens_in=100, tokens_out=50, cost_usd=0.001,
            raw_content=[{"type": "tool_use", **call}],
        )


@pytest.mark.asyncio
async def test_historical_checkpoint_forks_independent_workspace(tmp_path, monkeypatch):
    task = Task.load(REPO / "tasks/t01_fix_off_by_one")
    cfg = HarnessConfig.load(REPO / "harness")
    source = tmp_path / "source"
    target = tmp_path / "candidate"

    first_llm = WriteThenCrash()
    monkeypatch.setattr(runner_mod, "LLMClient", lambda: first_llm)
    with pytest.raises(RuntimeError, match="fork fixture crash"):
        await runner_mod.run_one(task, cfg, source, repeat=0, sandbox_kind="local")

    result = fork_native_run(
        source, target, task.task_id, REPO / "harness", repeat=0, step=1
    )
    assert result.checkpoint_step == 1
    assert result.prefix_tokens == 150
    assert result.parent_harness_version == result.target_harness_version

    run_key = f"{task.task_id}-r0"
    target_checkpoint = AgentCheckpointStore.read(
        target / "checkpoints" / f"{run_key}.json"
    )
    assert target_checkpoint.parent_run is not None
    assert target_checkpoint.final_result is None
    assert target_checkpoint.workspace_snapshot == "step-0001"

    source_workspace = source / "workspaces" / run_key
    target_workspace = target / "workspaces" / run_key
    source_workspace.joinpath("calc.py").write_text("SOURCE_MUTATED = True\n")
    assert "b + 1" in target_workspace.joinpath("calc.py").read_text()

    resume_llm = VerifyAndFinish()
    monkeypatch.setattr(runner_mod, "LLMClient", lambda: resume_llm)
    outcome = await runner_mod.run_one(
        task, cfg, target, repeat=0, sandbox_kind="local", resume=True
    )
    assert outcome.passed is True
    assert outcome.steps == 3
    assert resume_llm.calls == 2

    events = load_trace(target / "traces" / f"{run_key}.jsonl")
    assert sum(event["event_type"] == "fork" for event in events) == 1
    assert events[-1]["event_type"] == "termination"

    with pytest.raises(FileExistsError):
        fork_native_run(source, target, task.task_id, REPO / "harness", step=1)


@pytest.mark.asyncio
async def test_counterfactual_runner_reports_actual_continuation_spend(tmp_path, monkeypatch):
    task = Task.load(REPO / "tasks/t01_fix_off_by_one")
    cfg = HarnessConfig.load(REPO / "harness")
    source = tmp_path / "source"

    monkeypatch.setattr(runner_mod, "LLMClient", lambda: WriteThenCrash())
    with pytest.raises(RuntimeError, match="fork fixture crash"):
        await runner_mod.run_one(task, cfg, source, repeat=0, sandbox_kind="local")

    created = []

    def resumed_llm():
        llm = VerifyAndFinish()
        created.append(llm)
        return llm

    monkeypatch.setattr(runner_mod, "LLMClient", resumed_llm)
    report = await run_counterfactual(
        source,
        tmp_path / "experiment",
        REPO / "tasks",
        task.task_id,
        {"candidate-a": REPO / "harness", "candidate-b": REPO / "harness"},
        step=1,
        sandbox_kind="local",
    )

    assert report["aggregate"] == {
        "n_candidates": 2,
        "fork_passes": 2,
        "actual_continuation_tokens": 600,
        "actual_continuation_cost_usd": 0.004,
        "reused_prefix_tokens": 300,
        "reused_prefix_cost_usd": 0.002,
        "candidate_ranking": ["candidate-a", "candidate-b"],
    }
    assert len(created) == 2 and all(llm.calls == 2 for llm in created)
    for arm in report["arms"]:
        assert arm["fork"]["logical_total_tokens"] == 450
        assert arm["fork"]["continuation_usage"]["tokens"] == 300
        assert arm["full_rerun"] is None
    assert (tmp_path / "experiment" / "counterfactual_report.json").exists()


@pytest.mark.asyncio
async def test_counterfactual_optional_full_rerun_measures_savings(tmp_path, monkeypatch):
    task = Task.load(REPO / "tasks/t01_fix_off_by_one")
    cfg = HarnessConfig.load(REPO / "harness")
    source = tmp_path / "source"
    monkeypatch.setattr(runner_mod, "LLMClient", lambda: WriteThenCrash())
    with pytest.raises(RuntimeError, match="fork fixture crash"):
        await runner_mod.run_one(task, cfg, source, repeat=0, sandbox_kind="local")

    models = iter([VerifyAndFinish(), FullSolve()])
    monkeypatch.setattr(runner_mod, "LLMClient", lambda: next(models))
    report = await run_counterfactual(
        source,
        tmp_path / "experiment",
        REPO / "tasks",
        task.task_id,
        {"candidate": REPO / "harness"},
        step=1,
        sandbox_kind="local",
        include_full_rerun=True,
    )

    aggregate = report["aggregate"]
    assert aggregate["full_rerun_tokens"] == 450
    assert aggregate["actual_continuation_tokens"] == 300
    assert aggregate["token_savings_vs_full"] == 150
    assert aggregate["token_savings_fraction"] == pytest.approx(1 / 3)
    assert aggregate["cost_savings_usd_vs_full"] == 0.001
    assert aggregate["cost_savings_fraction"] == pytest.approx(1 / 3)
    assert aggregate["outcome_agreement"] == 1
    assert aggregate["outcome_agreement_count"] == 1
    assert aggregate["outcome_agreement_rate"] == 1.0
