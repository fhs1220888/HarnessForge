"""End-to-end loop test: scripted mock LLM + LocalSandbox on the t01 task.

No API calls, no Docker. Verifies:
- tool dispatch and message threading
- the run_tests_before_finish gate rejects a premature finish(done)
- test-run detection, termination, and trace/cost accounting
"""

import shutil
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

    async def complete(self, system, messages, tools=None, max_tokens=4096) -> LLMResponse:
        self.calls += 1
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
