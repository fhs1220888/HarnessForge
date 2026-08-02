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
from .checkpoint import AgentCheckpoint, AgentCheckpointStore, prompt_fingerprint
from .context import compact_messages, estimate_tokens
from .llm import LLMClient
from .memory import TaskMemory
from .tools import ToolExecutor
from .validation import build_schema_map, validate_tool_input


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
                 trace: TraceWriter, checkpoint: AgentCheckpointStore | None = None,
                 fault_exit_after_checkpoint: int | None = None):
        self.cfg = cfg
        self.llm = llm
        self.executor = executor
        self.trace = trace
        self.checkpoint = checkpoint
        self.fault_exit_after_checkpoint = fault_exit_after_checkpoint
        self._fault_injected = False

    async def run(self, task_prompt: str) -> TaskResult:
        p = self.cfg.policy
        max_steps = p("limits.max_steps", 30)
        max_tokens = p("limits.max_tokens_per_task", 200_000)
        max_cost = p("limits.max_cost_usd_per_task", 0.50)

        tools = _anthropic_tools(self.cfg)
        schema_map = build_schema_map(self.cfg.tool_descriptions)
        max_validation_errors = p("termination.consecutive_validation_errors", 4)
        memory_max_notes = p("memory.max_notes", 20)
        memory_max_chars = p("memory.max_chars_per_note", 1000)

        saved = (
            self.checkpoint.load(self.cfg.version, task_prompt)
            if self.checkpoint else None
        )
        if saved:
            completed = AgentCheckpointStore.restored_result(saved)
            if completed:
                return completed
            # The checkpoint is the authoritative budget ledger. The trace
            # normally contains the same counters, but recovery remains correct
            # if its final append was lost during the crash.
            self.trace.total_tokens_in = max(self.trace.total_tokens_in, saved.tokens_in)
            self.trace.total_tokens_out = max(self.trace.total_tokens_out, saved.tokens_out)
            self.trace.total_cost_usd = max(self.trace.total_cost_usd, saved.cost_usd)
            self.trace.emit(EventType.RESUME, {
                "next_step": saved.next_step,
                "tokens_in": saved.tokens_in,
                "tokens_out": saved.tokens_out,
                "cost_usd": saved.cost_usd,
                "workspace_snapshot": saved.workspace_snapshot,
            })
            messages = saved.messages
            memory = TaskMemory.restore(
                saved.memory_notes,
                max_notes=memory_max_notes,
                max_chars_per_note=memory_max_chars,
            )
            tests_ran = saved.tests_ran
            recent_actions = saved.recent_actions
            consecutive_validation_errors = saved.consecutive_validation_errors
            start_step = saved.next_step
        else:
            self.trace.emit(EventType.RUN_START, {
                "harness_version": self.cfg.version,
                "model": self.llm.model,
                "loop_policy": self.cfg.loop_policy,
            })
            messages: list[dict[str, Any]] = [{"role": "user", "content": task_prompt}]
            memory = TaskMemory(
                max_notes=memory_max_notes,
                max_chars_per_note=memory_max_chars,
            )
            tests_ran = False
            recent_actions: list[str] = []
            consecutive_validation_errors = 0
            start_step = 0

        def checkpoint_record(next_step: int) -> AgentCheckpoint:
            return AgentCheckpoint(
                harness_version=self.cfg.version,
                task_prompt_hash=prompt_fingerprint(task_prompt),
                next_step=next_step,
                messages=messages,
                tests_ran=tests_ran,
                recent_actions=recent_actions,
                consecutive_validation_errors=consecutive_validation_errors,
                memory_notes=memory.snapshot(),
                tokens_in=self.trace.total_tokens_in,
                tokens_out=self.trace.total_tokens_out,
                cost_usd=self.trace.total_cost_usd,
            )

        def persist(next_step: int) -> None:
            if not self.checkpoint:
                return
            record = checkpoint_record(next_step)
            write = self.checkpoint.save(record)
            self.trace.emit(EventType.CHECKPOINT, {
                "next_step": next_step,
                "n_messages": len(messages),
                "n_memory_notes": len(memory),
                "duration_s": round(write.duration_s, 6),
                "snapshot_files": write.snapshot_files,
                "snapshot_bytes": write.snapshot_bytes,
            })
            if (
                not self._fault_injected
                and self.fault_exit_after_checkpoint == next_step
            ):
                self._fault_injected = True
                self.trace.emit(EventType.FAULT_INJECTED, {
                    "after_checkpoint": next_step,
                    "mode": "controlled_process_exit",
                    "exit_code": 86,
                })
                # SystemExit is intentionally outside the runner's `Exception`
                # retry boundary. This exercises process-level recovery from a
                # checkpoint that has already been atomically committed.
                raise SystemExit(86)

        def terminate(exit_reason: str, status: str, steps: int) -> TaskResult:
            return self._terminate(
                exit_reason,
                status,
                steps,
                tests_ran,
                checkpoint_record(steps) if self.checkpoint else None,
            )

        if not saved:
            persist(0)

        for step in range(start_step, max_steps):
            # ---- budget guards -------------------------------------------------
            total_tokens = self.trace.total_tokens_in + self.trace.total_tokens_out
            if total_tokens > max_tokens:
                return terminate("max_tokens", "aborted", step)
            if self.trace.total_cost_usd > max_cost:
                return terminate("max_cost", "aborted", step)

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
            # Memory rides on the system prompt, outside the message history, so
            # compaction can never destroy it.
            system = self.cfg.system_prompt + memory.render()
            self.trace.emit(EventType.LLM_REQUEST,
                            {"n_messages": len(messages), "n_memory_notes": len(memory)})
            resp = await self.llm.complete(system, messages, tools)
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
                persist(step + 1)
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
                    messages.append({
                        "role": "user",
                        "content": [
                            self._tool_result_block(
                                call["id"],
                                f"Finish accepted: {status}",
                            )
                        ],
                    })
                    return terminate(f"finished_{status}", status, step + 1)

                # ---- pre-execution parameter validation -----------------------
                # Reject malformed tool arguments against the declared schema BEFORE
                # executing, and hand the model a precise repair message. Prevents
                # opaque in-tool crashes and gives arg-level malformed-output recovery.
                schema_err = validate_tool_input(schema_map.get(call["name"]), call["input"])
                if schema_err is not None:
                    consecutive_validation_errors += 1
                    self.trace.emit(EventType.VALIDATION_ERROR,
                                    {"tool": call["name"], "input": call["input"],
                                     "error": schema_err})
                    tool_results_content.append(
                        self._tool_result_block(call["id"], schema_err, is_error=True))
                    if consecutive_validation_errors >= max_validation_errors:
                        messages.append({"role": "user", "content": tool_results_content})
                        return terminate(
                            "repeated_validation_error", "aborted", step + 1
                        )
                    continue
                consecutive_validation_errors = 0

                # ---- memory writes (loop-handled, like finish; never hit the sandbox)
                if call["name"] == "memory_write":
                    confirmation = memory.write(call["input"]["key"], call["input"]["content"])
                    self.trace.emit(EventType.MEMORY_WRITE,
                                    {"key": call["input"]["key"],
                                     "content": call["input"]["content"][:500],
                                     "n_notes": len(memory)})
                    tool_results_content.append(
                        self._tool_result_block(call["id"], confirmation))
                    continue

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
                return terminate("repeated_action", "aborted", step + 1)

            persist(step + 1)

        return terminate("max_steps", "aborted", max_steps)

    # -------------------------------------------------------------------------
    @staticmethod
    def _tool_result_block(tool_use_id: str, content: str, is_error: bool = False) -> dict[str, Any]:
        return {"type": "tool_result", "tool_use_id": tool_use_id,
                "content": content, "is_error": is_error}

    def _terminate(
        self,
        exit_reason: str,
        status: str,
        steps: int,
        tests_ran: bool,
        checkpoint_record: AgentCheckpoint | None = None,
    ) -> TaskResult:
        result = TaskResult(
            task_id=self.trace.task_id, run_id=self.trace.run_id,
            exit_reason=exit_reason, status=status, steps=steps,
            tokens_in=self.trace.total_tokens_in, tokens_out=self.trace.total_tokens_out,
            cost_usd=self.trace.total_cost_usd, tests_ran=tests_ran,
        )
        if self.checkpoint:
            write = self.checkpoint.complete(result, checkpoint_record)
            self.trace.emit(EventType.CHECKPOINT, {
                "next_step": steps,
                "n_messages": len(checkpoint_record.messages) if checkpoint_record else 0,
                "n_memory_notes": (
                    len(checkpoint_record.memory_notes) if checkpoint_record else 0
                ),
                "duration_s": round(write.duration_s, 6),
                "snapshot_files": write.snapshot_files,
                "snapshot_bytes": write.snapshot_bytes,
                "completed": True,
            })
        self.trace.emit(EventType.TERMINATION, {"exit_reason": exit_reason, "status": status})
        return result


def _looks_like_test(command: str) -> bool:
    markers = ("pytest", "python -m unittest", "npm test", "make test", "check.sh")
    return any(m in command for m in markers)
