"""End-to-end memory tests: scripted mock LLM + LocalSandbox, no API/Docker.

The claim under test is the module's whole reason to exist: a note saved via
`memory_write` is still visible to the model AFTER compaction has destroyed the
tool result it came from.
"""

import dataclasses
import json
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


class RecordingScriptedLLM:
    """ScriptedLLM that also records the system prompt of every call."""

    model = "scripted-mock"

    def __init__(self, script: list[list[dict]]):
        self.script = list(script)
        self.calls = 0
        self.systems: list[str] = []

    async def complete(self, system, messages, tools=None, max_tokens=4096) -> LLMResponse:
        self.systems.append(system)
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


def _cfg_with_tiny_compaction() -> HarnessConfig:
    cfg = HarnessConfig.load(REPO / "harness")
    lp = json.loads(json.dumps(cfg.loop_policy))  # deep copy
    lp["context"]["compaction_trigger_tokens"] = 500
    lp["context"]["keep_last_n_tool_results"] = 1
    return dataclasses.replace(cfg, loop_policy=lp)


@pytest.mark.asyncio
async def test_memory_note_survives_compaction(tmp_path):
    workspace = tmp_path / "ws"
    shutil.copytree(REPO / "tasks/t01_fix_off_by_one/workspace", workspace)

    script = [
        # Save the note, then blow past the compaction trigger with a huge output.
        [{"name": "memory_write",
          "input": {"key": "root_cause", "content": "off-by-one: range(a, b) misses b"}}],
        [{"name": "bash", "input": {"command": "python -c \"print('A'*6000)\""}}],
        # keep_last_n=1: this result displaces the big one, which gets stubbed.
        [{"name": "write_file", "input": {"path": "calc.py", "content": FIXED_CALC}}],
        [{"name": "bash", "input": {"command": "python -m pytest tests/ -q"}}],
        [{"name": "finish", "input": {"status": "done", "summary": "fixed"}}],
    ]

    cfg = _cfg_with_tiny_compaction()
    llm = RecordingScriptedLLM(script)
    async with LocalSandbox(workspace) as sandbox:
        trace = TraceWriter(tmp_path / "traces", task_id="mem-e2e")
        loop = AgentLoop(cfg, llm, ToolExecutor(sandbox), trace)
        result = await loop.run("Fix the bug in calc.py, then run the tests.")

    assert result.status == "done"
    events = load_trace(trace.path)

    # Compaction actually happened and actually shrank the history (the big
    # 6000-char bash output is the compactable block).
    comps = [e for e in events if e["event_type"] == "compaction"]
    assert comps
    assert any(c["payload"]["tokens_after"] < c["payload"]["tokens_before"] for c in comps)
    assert all(c["payload"]["tokens_after"] <= c["payload"]["tokens_before"] for c in comps)

    # The memory write was traced with its content.
    mem = next(e for e in events if e["event_type"] == "memory_write")
    assert mem["payload"]["key"] == "root_cause"
    assert mem["payload"]["n_notes"] == 1

    # The core claim: on every LLM call after the write — including calls AFTER
    # compaction — the note is in the system prompt the model actually received.
    assert "root_cause" not in llm.systems[0]          # before the write
    for system in llm.systems[1:]:
        assert "off-by-one: range(a, b) misses b" in system


@pytest.mark.asyncio
async def test_malformed_memory_write_rejected_before_storing(tmp_path):
    """memory_write goes through the same pre-execution schema validation as
    every other tool: missing 'content' is rejected, nothing is stored."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    script = [
        [{"name": "memory_write", "input": {"key": "half_a_note"}}],  # no 'content'
        [{"name": "finish", "input": {"status": "gave_up", "summary": "stop"}}],
    ]
    cfg = HarnessConfig.load(REPO / "harness")
    llm = RecordingScriptedLLM(script)
    async with LocalSandbox(workspace) as sandbox:
        trace = TraceWriter(tmp_path / "traces", task_id="mem-val")
        loop = AgentLoop(cfg, llm, ToolExecutor(sandbox), trace)
        await loop.run("Do something.")

    events = load_trace(trace.path)
    val = [e for e in events if e["event_type"] == "validation_error"]
    assert len(val) == 1 and "content" in val[0]["payload"]["error"]
    assert not any(e["event_type"] == "memory_write" for e in events)
    assert all("half_a_note" not in s for s in llm.systems)  # nothing injected
