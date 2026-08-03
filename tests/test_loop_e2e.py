"""End-to-end loop test: scripted mock LLM + LocalSandbox on the t01 task.

No API calls, no Docker. Verifies:
- tool dispatch and message threading
- the run_tests_before_finish gate rejects a premature finish(done)
- test-run detection, termination, and trace/cost accounting
"""

import shutil
import sys
import copy
from pathlib import Path

import pytest

from harnessforge.agent.llm import LLMResponse
from harnessforge.agent.loop import AgentLoop
from harnessforge.agent.tools import ToolExecutor
from harnessforge.config import HarnessConfig
from harnessforge.sandbox.local_sandbox import LocalSandbox
from harnessforge.trace import TraceWriter, load_trace

REPO = Path(__file__).parents[1]

FIXED_CALC = '''def sum_range(a: int, b: int) -> int:
    """Sum integers from a to b inclusive."""
    return sum(range(a, b + 1))
'''


class ScriptedLLM:
    """Replays a fixed sequence of tool calls; ignores its inputs."""

    model = "scripted-mock"

    def __init__(self, script: list[list[dict]]):
        self.script = list(script)
        self.calls = 0
        self.max_tokens_seen: list[int] = []

    async def complete(self, system, messages, tools=None, max_tokens=4096) -> LLMResponse:
        self.calls += 1
        self.max_tokens_seen.append(max_tokens)
        if not self.script:
            pytest.fail("mock LLM ran out of scripted steps — loop did not terminate")
        tool_calls = [
            {"id": f"tu_{self.calls}_{i}", "name": c["name"], "input": c["input"]}
            for i, c in enumerate(self.script.pop(0))
        ]
        raw = [{"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc["input"]}
               for tc in tool_calls]
        return LLMResponse(text="", tool_calls=tool_calls, stop_reason="tool_use",
                           tokens_in=100, tokens_out=50, cost_usd=0.0005, raw_content=raw)


def _verifier_config(
    min_successful_commands: int = 1,
    require_final_state_audit: bool = False,
) -> HarnessConfig:
    base = HarnessConfig.load(REPO / "harness_selfverify")
    policy = copy.deepcopy(base.loop_policy)
    policy["limits"]["max_steps"] = 12
    policy["verification"] = {
        "enforce_before_finish": True,
        "min_successful_commands": min_successful_commands,
        "require_final_state_audit": require_final_state_audit,
        "final_state_min_successful_commands": 1,
    }
    return HarnessConfig(
        system_prompt=base.system_prompt,
        tool_descriptions=base.tool_descriptions,
        loop_policy=policy,
        version="test-verifier",
    )


@pytest.mark.asyncio
async def test_full_loop_fixes_task(tmp_path):
    workspace = tmp_path / "ws"
    shutil.copytree(REPO / "tasks/t01_fix_off_by_one/workspace", workspace)

    script = [
        [{"name": "read_file", "input": {"path": "calc.py"}}],
        # Premature finish: must be rejected because no tests were run yet.
        [{"name": "finish", "input": {"status": "done", "summary": "too early"}}],
        [{"name": "write_file", "input": {"path": "calc.py", "content": FIXED_CALC}}],
        [{"name": "bash", "input": {"command": "python -m pytest tests/ -q"}}],
        [{"name": "finish", "input": {"status": "done", "summary": "fixed off-by-one"}}],
    ]

    cfg = HarnessConfig.load(REPO / "harness")
    async with LocalSandbox(workspace) as sandbox:
        trace = TraceWriter(tmp_path / "traces", task_id="t01-e2e")
        loop = AgentLoop(cfg, ScriptedLLM(script), ToolExecutor(sandbox), trace)
        result = await loop.run("Fix the bug in calc.py, then run the tests.")

        # Ground-truth check, same as the eval runner would do.
        check = await sandbox.run("python -m pytest tests/ -q")

    assert result.status == "done"
    assert result.exit_reason == "finished_done"
    assert result.tests_ran is True
    assert check.exit_code == 0, check.stdout + check.stderr
    assert result.cost_usd > 0

    events = load_trace(trace.path)
    types = [e["event_type"] for e in events]
    assert types[0] == "run_start" and types[-1] == "termination"
    assert "test_run" in types
    test_ev = next(e for e in events if e["event_type"] == "test_run")
    assert test_ev["payload"]["passed"] is True


@pytest.mark.asyncio
async def test_malformed_tool_args_rejected_then_recovers(tmp_path):
    """A bad tool call (missing required 'command') must be rejected pre-execution
    with a repair message, and the agent recovers on the next turn."""
    workspace = tmp_path / "ws"
    shutil.copytree(REPO / "tasks/t01_fix_off_by_one/workspace", workspace)

    script = [
        [{"name": "bash", "input": {"timeout_s": 5}}],            # malformed: no 'command'
        [{"name": "write_file", "input": {"path": "calc.py", "content": FIXED_CALC}}],
        [{"name": "bash", "input": {"command": "python -m pytest tests/ -q"}}],
        [{"name": "finish", "input": {"status": "done", "summary": "recovered"}}],
    ]
    cfg = HarnessConfig.load(REPO / "harness")
    async with LocalSandbox(workspace) as sandbox:
        trace = TraceWriter(tmp_path / "traces", task_id="valfix")
        loop = AgentLoop(cfg, ScriptedLLM(script), ToolExecutor(sandbox), trace)
        result = await loop.run("Fix calc.py, then run the tests.")
        check = await sandbox.run("python -m pytest tests/ -q")

    assert result.status == "done"
    assert check.exit_code == 0
    events = load_trace(trace.path)
    val = [e for e in events if e["event_type"] == "validation_error"]
    assert len(val) == 1 and "command" in val[0]["payload"]["error"]
    # the malformed call was NOT executed (no tool_call for that bash with only timeout_s)
    bad_calls = [e for e in events if e["event_type"] == "tool_call"
                 and e["payload"].get("tool") == "bash"
                 and "command" not in e["payload"].get("input", {})]
    assert bad_calls == []


@pytest.mark.asyncio
async def test_local_sandbox_exposes_current_python_as_python(tmp_path):
    """Local runs must use the interpreter that launched HarnessForge.

    This protects macOS environments that provide `python3` but no global
    `python`, and direct `.venv/bin/pytest` invocations that do not activate PATH.
    """
    async with LocalSandbox(tmp_path) as sandbox:
        result = await sandbox.run(
            "python -c 'import pathlib,sys; print(pathlib.Path(sys.executable).resolve())'"
        )
    assert result.exit_code == 0, result.stderr
    assert Path(result.stdout.strip()).resolve() == Path(sys.executable).resolve()


@pytest.mark.asyncio
async def test_loop_aborts_on_repeated_validation_errors(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    # distinct-but-all-malformed calls (missing 'command'), so the repeated-action
    # guard doesn't pre-empt the validation-error guard we're testing here.
    script = [[{"name": "bash", "input": {"timeout_s": i}}] for i in range(1, 6)]
    cfg = HarnessConfig.load(REPO / "harness")
    async with LocalSandbox(workspace) as sandbox:
        trace = TraceWriter(tmp_path / "traces", task_id="valabort")
        loop = AgentLoop(cfg, ScriptedLLM(script), ToolExecutor(sandbox), trace)
        result = await loop.run("Do something.")
    assert result.exit_reason == "repeated_validation_error"
    assert result.status == "aborted"


@pytest.mark.asyncio
async def test_loop_aborts_on_repeated_action(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    same = [{"name": "bash", "input": {"command": "echo stuck"}}]
    script = [same, same, same, same, same]

    cfg = HarnessConfig.load(REPO / "harness")
    async with LocalSandbox(workspace) as sandbox:
        trace = TraceWriter(tmp_path / "traces", task_id="stuck-e2e")
        loop = AgentLoop(cfg, ScriptedLLM(script), ToolExecutor(sandbox), trace)
        result = await loop.run("Do something.")

    assert result.exit_reason == "repeated_action"
    assert result.status == "aborted"


@pytest.mark.asyncio
async def test_verifier_defers_finish_until_post_finish_evidence(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    script = [
        [{"name": "finish", "input": {"status": "done", "summary": "looks done"}}],
        [{"name": "finish", "input": {"status": "done", "summary": "still done"}}],
        [{"name": "bash", "input": {"command": "test -d ."}}],
        [{"name": "finish", "input": {"status": "done", "summary": "verified"}}],
    ]

    async with LocalSandbox(workspace) as sandbox:
        trace = TraceWriter(tmp_path / "traces", task_id="verify-gate")
        llm = ScriptedLLM(script)
        cfg = _verifier_config()
        policy = copy.deepcopy(cfg.loop_policy)
        policy["limits"]["max_output_tokens_per_call"] = 12345
        cfg = HarnessConfig(
            system_prompt=cfg.system_prompt,
            tool_descriptions=cfg.tool_descriptions,
            loop_policy=policy,
            version=cfg.version,
        )
        loop = AgentLoop(cfg, llm, ToolExecutor(sandbox), trace)
        result = await loop.run("Create and verify the requested deliverable.")

    assert result.exit_reason == "finished_done"
    assert result.steps == 4
    assert llm.max_tokens_seen == [12345] * 4
    types = [event["event_type"] for event in load_trace(trace.path)]
    assert types.count("verification_start") == 1
    assert types.count("verification_rejected") == 1
    assert types.count("verification_evidence") == 1
    assert types.count("verification_passed") == 1


@pytest.mark.asyncio
async def test_verifier_resets_evidence_after_edit(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    script = [
        [{"name": "finish", "input": {"status": "done", "summary": "first pass"}}],
        [{"name": "bash", "input": {"command": "test -d ."}}],
        [{"name": "write_file", "input": {"path": "answer.txt", "content": "fixed\n"}}],
        [{"name": "finish", "input": {"status": "done", "summary": "edited"}}],
        [{"name": "bash", "input": {"command": "test \"$(cat answer.txt)\" = fixed"}}],
        [{"name": "finish", "input": {"status": "done", "summary": "reverified"}}],
    ]

    async with LocalSandbox(workspace) as sandbox:
        trace = TraceWriter(tmp_path / "traces", task_id="verify-reset")
        loop = AgentLoop(
            _verifier_config(), ScriptedLLM(script), ToolExecutor(sandbox), trace
        )
        result = await loop.run("Write answer.txt.")

    assert result.exit_reason == "finished_done"
    events = load_trace(trace.path)
    resets = [event for event in events if event["event_type"] == "verification_reset"]
    assert len(resets) == 1
    assert resets[0]["payload"]["prior_successful_commands"] == 1
    assert sum(event["event_type"] == "verification_evidence" for event in events) == 2


@pytest.mark.asyncio
async def test_verifier_resets_evidence_after_failed_command(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    script = [
        [{"name": "finish", "input": {"status": "done", "summary": "first pass"}}],
        [{"name": "bash", "input": {"command": "test -d ."}}],
        [{"name": "bash", "input": {"command": "false"}}],
        [{"name": "finish", "input": {"status": "done", "summary": "not enough"}}],
        [{"name": "bash", "input": {"command": "test -d ."}}],
        [{"name": "finish", "input": {"status": "done", "summary": "verified"}}],
    ]

    async with LocalSandbox(workspace) as sandbox:
        trace = TraceWriter(tmp_path / "traces", task_id="verify-failure")
        loop = AgentLoop(
            _verifier_config(), ScriptedLLM(script), ToolExecutor(sandbox), trace
        )
        result = await loop.run("Verify the workspace.")

    assert result.exit_reason == "finished_done"
    events = load_trace(trace.path)
    resets = [event for event in events if event["event_type"] == "verification_reset"]
    assert resets[0]["payload"]["reason"] == "failed_verification_command"
    assert resets[0]["payload"]["prior_successful_commands"] == 1
    assert sum(event["event_type"] == "verification_rejected" for event in events) == 1


@pytest.mark.asyncio
async def test_verifier_requires_final_state_audit(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    script = [
        [{"name": "finish", "input": {"status": "done", "summary": "implemented"}}],
        [{"name": "bash", "input": {"command": "touch test-binary; test -f test-binary"}}],
        [{"name": "finish", "input": {"status": "done", "summary": "behavior works"}}],
        [{"name": "bash", "input": {"command": "rm test-binary; test ! -e test-binary"}}],
        [{"name": "finish", "input": {"status": "done", "summary": "clean final state"}}],
    ]

    async with LocalSandbox(workspace) as sandbox:
        trace = TraceWriter(tmp_path / "traces", task_id="verify-final-state")
        loop = AgentLoop(
            _verifier_config(require_final_state_audit=True),
            ScriptedLLM(script),
            ToolExecutor(sandbox),
            trace,
        )
        result = await loop.run("Create one deliverable without test artifacts.")

    assert result.exit_reason == "finished_done"
    assert not (workspace / "test-binary").exists()
    events = load_trace(trace.path)
    types = [event["event_type"] for event in events]
    assert types.count("verification_final_audit") == 1
    passed = next(
        event for event in events if event["event_type"] == "verification_passed"
    )
    assert passed["payload"]["final_state_audited"] is True
