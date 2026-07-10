"""Tool implementations. FIXED in v1 — only the *descriptions* the model sees
(harness/tool_descriptions.yaml) are evolvable.

Each tool returns a ToolResult; the loop feeds .output back to the model and
logs everything to the trace.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..sandbox.docker_sandbox import Sandbox


@dataclass
class ToolResult:
    output: str
    exit_code: int = 0
    error: bool = False
    duration_s: float = 0.0


class ToolExecutor:
    def __init__(self, sandbox: Sandbox, max_output_chars: int = 8000):
        self.sandbox = sandbox
        self.max_output_chars = max_output_chars

    def _truncate(self, s: str) -> str:
        if len(s) <= self.max_output_chars:
            return s
        half = self.max_output_chars // 2
        return s[:half] + f"\n... [{len(s) - self.max_output_chars} chars truncated] ...\n" + s[-half:]

    async def execute(self, name: str, tool_input: dict[str, Any]) -> ToolResult:
        handler = getattr(self, f"_tool_{name}", None)
        if handler is None:
            return ToolResult(output=f"Unknown tool: {name}", error=True, exit_code=1)
        try:
            result: ToolResult = await handler(tool_input)
        except Exception as e:  # tool errors go back to the model, never crash the loop
            return ToolResult(output=f"Tool error: {type(e).__name__}: {e}", error=True, exit_code=1)
        result.output = self._truncate(result.output)
        return result

    async def _tool_bash(self, inp: dict[str, Any]) -> ToolResult:
        res = await self.sandbox.run(inp["command"], timeout_s=inp.get("timeout_s", 60))
        out = res.stdout + (("\n[stderr]\n" + res.stderr) if res.stderr else "")
        return ToolResult(output=out or "(no output)", exit_code=res.exit_code,
                          error=res.exit_code != 0, duration_s=res.duration_s)

    async def _tool_read_file(self, inp: dict[str, Any]) -> ToolResult:
        offset, limit = inp.get("offset", 0), inp.get("limit", 500)
        content = await self.sandbox.read_file(inp["path"])
        lines = content.splitlines()[offset : offset + limit]
        numbered = "\n".join(f"{i + 1 + offset:6d}\t{line}" for i, line in enumerate(lines))
        return ToolResult(output=numbered or "(empty file)")

    async def _tool_write_file(self, inp: dict[str, Any]) -> ToolResult:
        await self.sandbox.write_file(inp["path"], inp["content"])
        return ToolResult(output=f"Wrote {len(inp['content'])} chars to {inp['path']}")

    async def _tool_apply_patch(self, inp: dict[str, Any]) -> ToolResult:
        # Atomic: sandbox.apply_patch must roll back on any hunk failure.
        res = await self.sandbox.apply_patch(inp["patch"])
        return ToolResult(output=res.stdout or "Patch applied.",
                          exit_code=res.exit_code, error=res.exit_code != 0)

    async def _tool_finish(self, inp: dict[str, Any]) -> ToolResult:
        # Handled by the loop as a termination signal; implemented here so the
        # executor never sees it as unknown.
        return ToolResult(output=f"[finish] {inp.get('status')}: {inp.get('summary', '')}")
