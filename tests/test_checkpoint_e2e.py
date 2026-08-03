"""Crash-injection tests for turn-boundary episode recovery."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from harnessforge.agent.checkpoint import (
    AgentCheckpoint,
    AgentCheckpointStore,
    CheckpointMismatchError,
    prompt_fingerprint,
)
from harnessforge.agent.llm import LLMResponse
from harnessforge.agent.loop import AgentLoop
from harnessforge.agent.tools import ToolExecutor
from harnessforge.config import HarnessConfig
from harnessforge.eval import runner as runner_mod
from harnessforge.eval.fork import fork_native_run
from harnessforge.eval.task import Task
from harnessforge.sandbox.local_sandbox import LocalSandbox
from harnessforge.trace import TraceWriter, load_trace

REPO = Path(__file__).parents[1]
FIXED_CALC = '''def sum_range(a: int, b: int) -> int:
    """Sum integers from a to b inclusive."""
    return sum(range(a, b + 1))
'''


class ScriptThenCrashLLM:
    model = "script-then-crash"

    def __init__(self):
        self.calls = 0

    async def complete(self, *_args, **_kwargs):
        self.calls += 1
        if self.calls == 2:
            raise RuntimeError("injected process crash")
        call = {
            "id": "write-1",
            "name": "write_file",
            "input": {"path": "calc.py", "content": FIXED_CALC},
        }
        return LLMResponse(
            text="",
            tool_calls=[call],
            stop_reason="tool_use",
            tokens_in=100,
            tokens_out=50,
            cost_usd=0.001,
            raw_content=[{"type": "tool_use", **call}],
        )


class ResumeLLM:
    model = "resume-script"

    def __init__(self):
        self.calls = 0

    async def complete(self, *_args, **_kwargs):
        self.calls += 1
        if self.calls == 1:
            call = {
                "id": "test-1",
                "name": "bash",
                "input": {"command": "python -m pytest tests/ -q"},
            }
        elif self.calls == 2:
            call = {
                "id": "finish-1",
                "name": "finish",
                "input": {"status": "done", "summary": "resumed and verified"},
            }
        else:
            pytest.fail("completed checkpoint unexpectedly called the model again")
        return LLMResponse(
            text="",
            tool_calls=[call],
            stop_reason="tool_use",
            tokens_in=100,
            tokens_out=50,
            cost_usd=0.001,
            raw_content=[{"type": "tool_use", **call}],
        )


class NeverCallLLM:
    model = "must-not-run"

    async def complete(self, *_args, **_kwargs):
        pytest.fail("a completed episode must return from its checkpoint")


@pytest.mark.asyncio
async def test_crash_resumes_from_last_committed_turn(tmp_path):
    workspace = tmp_path / "workspace"
    shutil.copytree(REPO / "tasks/t01_fix_off_by_one/workspace", workspace)
    checkpoint = AgentCheckpointStore(tmp_path / "checkpoints" / "run.json")
    cfg = HarnessConfig.load(REPO / "harness")
    prompt = "Fix calc.py and run the tests."

    first_llm = ScriptThenCrashLLM()
    async with LocalSandbox(workspace) as sandbox:
        trace = TraceWriter(tmp_path / "traces", task_id="resume-e2e", run_id="resume-e2e")
        loop = AgentLoop(
            cfg, first_llm, ToolExecutor(sandbox), trace, checkpoint=checkpoint
        )
        with pytest.raises(RuntimeError, match="injected process crash"):
            await loop.run(prompt)

    # The write tool completed and the following turn boundary was committed.
    assert first_llm.calls == 2
    assert "b + 1" in (workspace / "calc.py").read_text()
    saved = checkpoint.load(cfg.version, prompt)
    assert saved is not None and saved.next_step == 1 and saved.final_result is None

    resume_llm = ResumeLLM()
    async with LocalSandbox(workspace) as sandbox:
        resumed_trace = TraceWriter(
            tmp_path / "traces",
            task_id="resume-e2e",
            run_id="resume-e2e",
            resume=True,
        )
        resumed = AgentLoop(
            cfg, resume_llm, ToolExecutor(sandbox), resumed_trace, checkpoint=checkpoint
        )
        result = await resumed.run(prompt)

    assert result.status == "done"
    assert result.tests_ran is True
    assert result.steps == 3
    assert result.tokens_in == 300
    assert resume_llm.calls == 2

    events = load_trace(resumed_trace.path)
    assert sum(event["event_type"] == "run_start" for event in events) == 1
    assert events[-1]["event_type"] == "termination"
    assert any(event["event_type"] == "checkpoint" for event in events)

    # A crash after termination but before the suite result is recorded does not
    # spend another model call: the completed result itself is checkpointed.
    async with LocalSandbox(workspace) as sandbox:
        final_trace = TraceWriter(
            tmp_path / "traces",
            task_id="resume-e2e",
            run_id="resume-e2e",
            resume=True,
        )
        restored = AgentLoop(
            cfg, NeverCallLLM(), ToolExecutor(sandbox), final_trace, checkpoint=checkpoint
        )
        result_again = await restored.run(prompt)
    assert result_again == result


def test_checkpoint_refuses_prompt_or_harness_drift(tmp_path):
    path = tmp_path / "checkpoint.json"
    store = AgentCheckpointStore(path)
    from harnessforge.agent.checkpoint import AgentCheckpoint, prompt_fingerprint

    store.save(AgentCheckpoint(
        harness_version="h1",
        task_prompt_hash=prompt_fingerprint("original"),
        next_step=0,
        messages=[],
    ))
    with pytest.raises(CheckpointMismatchError, match="harness"):
        store.load("h2", "original")
    with pytest.raises(CheckpointMismatchError, match="prompt"):
        store.load("h1", "changed")


def test_checkpoint_roundtrips_verifier_state(tmp_path):
    store = AgentCheckpointStore(tmp_path / "checkpoint.json")
    store.save(AgentCheckpoint(
        harness_version="verifier-v1",
        task_prompt_hash=prompt_fingerprint("task"),
        next_step=7,
        messages=[],
        verification_active=True,
        verification_round=1,
        verification_successful_commands=2,
        verification_final_audit_active=True,
    ))

    restored = store.load("verifier-v1", "task")
    assert restored is not None
    assert restored.verification_active is True
    assert restored.verification_round == 1
    assert restored.verification_successful_commands == 2
    assert restored.verification_final_audit_active is True


@pytest.mark.asyncio
async def test_native_runner_keeps_workspace_and_episode_for_resume(tmp_path, monkeypatch):
    task = Task.load(REPO / "tasks/t01_fix_off_by_one")
    cfg = HarnessConfig.load(REPO / "harness")
    out = tmp_path / "run"
    first_llm = ScriptThenCrashLLM()
    monkeypatch.setattr(runner_mod, "LLMClient", lambda: first_llm)

    with pytest.raises(RuntimeError, match="injected process crash"):
        await runner_mod.run_one(task, cfg, out, repeat=0, sandbox_kind="local")

    workspace = out / "workspaces" / "t01_fix_off_by_one-r0"
    checkpoint = out / "checkpoints" / "t01_fix_off_by_one-r0.json"
    assert workspace.exists() and checkpoint.exists()
    assert "b + 1" in (workspace / "calc.py").read_text()

    # Simulate an uncommitted mid-tool filesystem mutation after the last safe
    # checkpoint. Resume must roll the workspace back before continuing.
    (workspace / "calc.py").write_text("BROKEN_AFTER_CHECKPOINT = True\n")

    resume_llm = ResumeLLM()
    monkeypatch.setattr(runner_mod, "LLMClient", lambda: resume_llm)
    outcome = await runner_mod.run_one(
        task, cfg, out, repeat=0, sandbox_kind="local", resume=True
    )

    assert outcome.passed is True
    assert outcome.exit_reason == "finished_done"
    assert outcome.steps == 3
    assert "BROKEN_AFTER_CHECKPOINT" not in (workspace / "calc.py").read_text()
    events = load_trace(out / "traces" / "t01_fix_off_by_one-r0.jsonl")
    assert sum(event["event_type"] == "run_start" for event in events) == 1


@pytest.mark.asyncio
async def test_explicit_checkpoint_fault_exits_process_then_resumes(tmp_path, monkeypatch):
    task = Task.load(REPO / "tasks/t01_fix_off_by_one")
    cfg = HarnessConfig.load(REPO / "harness")
    out = tmp_path / "run"
    first_llm = ScriptThenCrashLLM()
    monkeypatch.setattr(runner_mod, "LLMClient", lambda: first_llm)

    with pytest.raises(SystemExit) as crash:
        await runner_mod.run_one(
            task,
            cfg,
            out,
            repeat=0,
            sandbox_kind="local",
            fault_exit_after_checkpoint=1,
        )
    assert crash.value.code == 86
    assert first_llm.calls == 1

    checkpoint = AgentCheckpointStore(
        out / "checkpoints" / "t01_fix_off_by_one-r0.json"
    ).load(cfg.version, task.prompt)
    assert checkpoint is not None
    assert checkpoint.next_step == 1
    assert checkpoint.tokens_in + checkpoint.tokens_out == 150

    resume_llm = ResumeLLM()
    monkeypatch.setattr(runner_mod, "LLMClient", lambda: resume_llm)
    outcome = await runner_mod.run_one(
        task, cfg, out, repeat=0, sandbox_kind="local", resume=True
    )

    assert outcome.passed is True
    assert outcome.tokens == 450
    completed = AgentCheckpointStore(
        out / "checkpoints" / "t01_fix_off_by_one-r0.json"
    ).load(cfg.version, task.prompt)
    assert completed is not None and completed.final_result is not None
    assert completed.next_step == outcome.steps
    assert completed.tokens_in + completed.tokens_out == outcome.tokens
    assert completed.messages[-1]["role"] == "user"

    forked = tmp_path / "forked-after-completion"
    fork_native_run(
        out,
        forked,
        task.task_id,
        REPO / "harness",
    )
    fork_checkpoint = AgentCheckpointStore.read(
        forked / "checkpoints" / "t01_fix_off_by_one-r0.json"
    )
    assert fork_checkpoint.final_result is None
    assert fork_checkpoint.next_step == outcome.steps
    assert fork_checkpoint.tokens_in + fork_checkpoint.tokens_out == outcome.tokens
    assert fork_checkpoint.messages[-1]["role"] == "user"

    events = load_trace(out / "traces" / "t01_fix_off_by_one-r0.jsonl")
    assert sum(event["event_type"] == "fault_injected" for event in events) == 1
    assert sum(event["event_type"] == "resume" for event in events) == 1
