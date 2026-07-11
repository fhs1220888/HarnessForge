"""The agent loop: plan → tool call → observation → repeat, under loop_policy limits.

All behavior knobs come from HarnessConfig (the evolvable genome); this file is
fixed runtime code in v1.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..config import HarnessConfig
from ..trace import EventType, TraceWriter
from .context import compact_messages, estimate_tokens
from .llm import LLMClient
from .tools import ToolExecutor


@dataclass
class TaskResult:
    task_id: str
    run_id: str
    exit_reason: str          # one of trace.EXIT_REASONS
    status: str               # done | gave_up | aborted
    steps: int
    tokens_in: int
    tokens_out: int
    cost_usd: float
    tests_ran: bool


def _anthropic_tools(cfg: HarnessConfig) -> list[dict[str, Any]]:
    return [
        {"name": t["name"], "description": t["description"], "input_schema": t["input_schema"]}
        for t in cfg.tool_descriptions["tools"]
    ]


class AgentLoop:
    def __init__(self, cfg: HarnessConfig, llm: LLMClient, executor: ToolExecutor,
                 trace: TraceWriter):
        self.cfg = cfg
        self.llm = llm
        self.executor = executor
        self.trace = trace

    async def run(self, task_prompt: str) -> TaskResult:
        p = self.cfg.policy
        max_steps = p("limits.max_steps", 30)
        max_tokens = p("limits.max_tokens_per_task", 200_000)
        max_cost = p("limits.max_cost_usd_per_task", 0.50)

        self.trace.emit(EventType.RUN_START, {
            "harness_version": self.cfg.version,
            "model": self.llm.model,
            "loop_policy": self.cfg.loop_policy,
        })

        messages: list[dict[str, Any]] = [{"role": "user", "content": task_prompt}]
        tools = _anthropic_tools(self.cfg)
        tests_ran = False
        recent_actions: list[str] = []

        for step in range(max_steps):
            # ---- budget guards -------------------------------------------------
            total_tokens = self.trace.total_tokens_in + self.trace.total_tokens_out
            if total_tokens > max_tokens:
                return self._terminate("max_tokens", "aborted", step, tests_ran)
            if self.trace.total_cost_usd > max_cost:
                return self._terminate("max_cost", "aborted", step, tests_ran)

            # ---- context compaction -------------------------------------------
            trigger = p("context.compaction_trigger_tokens", 120_000)
            if estimate_tokens(messages) > trigger:
                messages, before, after = compact_messages(
                    messages, keep_last_n=p("context.keep_last_n_tool_results", 5))
                self.trace.emit(EventType.COMPACTION, {
                    "tokens_before": before, "tokens_after": after,
                    "strategy": "truncate_old_tool_results",
                })

            # ---- model call ----------------------------------------------------
            self.trace.emit(EventType.LLM_REQUEST, {"n_messages": len(messages)})
            resp = await self.llm.complete(self.cfg.system_prompt, messages, tools)
            self.trace.emit(EventType.LLM_RESPONSE,
                            {"text": resp.text[:2000], "n_tool_calls": len(resp.tool_calls),
                             "stop_reason": resp.stop_reason},
                            tokens_in=resp.tokens_in, tokens_out=resp.tokens_out,
                            cost_usd=resp.cost_usd)

            if not resp.tool_calls:
                # Model responded with text only; nudge it to use tools or finish.
                messages.append({"role": "assistant", "content": resp.text or "..."})
                messages.append({"role": "user",
                                 "content": "Use a tool to make progress, or call `finish`."})
                continue

            messages.append({"role": "assistant", "content": resp.raw_content})

            # ---- execute tool calls -------------------------------------------
            tool_results_content: list[dict[str, Any]] = []
            for call in resp.tool_calls:
                sig = json.dumps({"n": call["name"], "i": call["input"]}, sort_keys=True)
                recent_actions.append(sig)

                if call["name"] == "finish":
                    status = call["input"].get("status", "done")
                    if (status == "done"
                            and p("testing.run_tests_before_finish", True) and not tests_ran):
                        tool_results_content.append(self._tool_result_block(
                            call["id"], "Rejected: run the task's tests before finishing.",
                            is_error=True))
                        continue
                    self.trace.emit(EventType.TOOL_CALL, {"tool": "finish", "input": call["input"]})
                    return self._terminate(f"finished_{status}", status, step + 1, tests_ran)

                self.trace.emit(EventType.TOOL_CALL, {"tool": call["name"], "input": call["input"]})
                result = await self.executor.execute(call["name"], call["input"])
                self.trace.emit(EventType.TOOL_RESULT,
                                {"tool": call["name"], "exit_code": result.exit_code,
                                 "error": result.error, "duration_s": result.duration_s,
                                 "output": result.output[:2000]})

                if call["name"] == "bash" and _looks_like_test(call["input"].get("command", "")):
                    tests_ran = True
                    self.trace.emit(EventType.TEST_RUN,
                                    {"command": call["input"]["command"],
                                     "passed": result.exit_code == 0,
                                     "output": result.output[:2000]})

                tool_results_content.append(
                    self._tool_result_block(call["id"], result.output, is_error=result.error))

            messages.append({"role": "user", "content": tool_results_content})

            # ---- termination heuristics ---------------------------------------
            n_ident = p("termination.consecutive_identical_actions", 3)
            if len(recent_actions) >= n_ident and len(set(recent_actions[-n_ident:])) == 1:
                return self._terminate("repeated_action", "aborted", step + 1, tests_ran)

        return self._terminate("max_steps", "aborted", max_steps, tests_ran)

    # -------------------------------------------------------------------------
    @staticmethod
    def _tool_result_block(tool_use_id: str, content: str, is_error: bool = False) -> dict[str, Any]:
        return {"type": "tool_result", "tool_use_id": tool_use_id,
                "content": content, "is_error": is_error}

    def _terminate(self, exit_reason: str, status: str, steps: int, tests_ran: bool) -> TaskResult:
        self.trace.emit(EventType.TERMINATION, {"exit_reason": exit_reason, "status": status})
        return TaskResult(
            task_id=self.trace.task_id, run_id=self.trace.run_id,
            exit_reason=exit_reason, status=status, steps=steps,
            tokens_in=self.trace.total_tokens_in, tokens_out=self.trace.total_tokens_out,
            cost_usd=self.trace.total_cost_usd, tests_ran=tests_ran,
        )


def _looks_like_test(command: str) -> bool:
    markers = ("pytest", "python -m unittest", "npm test", "make test", "check.sh")
    return any(m in command for m in markers)
