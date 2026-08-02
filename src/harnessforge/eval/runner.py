"""Eval runner: run the harness over a task suite, write results + traces.

Output layout:
    runs/<run_name>/
        results.jsonl     # one TaskOutcome per task per repeat
        traces/           # one JSONL trace per task run
        summary.json      # aggregate: pass rate, cost, exit-reason histogram

Usage:
    python -m harnessforge.eval.runner --tasks tasks/ --out runs/baseline --repeats 3
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from ..agent.llm import (
    LLMClient,
    UnretryableLLMError,
    configured_temperature,
    pricing_revision,
)
from ..agent.loop import AgentLoop
from ..agent.checkpoint import AgentCheckpointStore
from ..agent.tools import ToolExecutor
from ..config import HarnessConfig
from ..sandbox.docker_sandbox import Sandbox
from ..sandbox.local_sandbox import LocalSandbox
from ..trace import TraceWriter
from .persistence import ResultSink
from .stats import (
    RunManifest,
    repository_is_dirty,
    repository_revision,
    suite_hash,
    tree_hash,
)
from .task import Task, discover_tasks

SANDBOXES = {"docker": Sandbox, "local": LocalSandbox}


@dataclass
class TaskOutcome:
    task_id: str
    repeat: int
    run_id: str
    passed: bool
    exit_reason: str
    steps: int
    cost_usd: float
    tokens: int
    harness_version: str
    check_tail: str = ""  # last chars of the check command's output, for debugging


async def run_one(task: Task, cfg: HarnessConfig, out_dir: Path, repeat: int,
                  sandbox_kind: str = "docker", resume: bool = False,
                  fault_exit_after_checkpoint: int | None = None) -> TaskOutcome:
    run_key = f"{task.task_id}-r{repeat}"
    workspace = out_dir / "workspaces" / run_key
    checkpoint = AgentCheckpointStore(
        out_dir / "checkpoints" / f"{run_key}.json",
        workspace=workspace,
        snapshots_dir=out_dir / "workspace_snapshots" / run_key,
        history_dir=out_dir / "checkpoint_history" / run_key,
    )

    if not resume:
        checkpoint.clear()
        if workspace.exists():
            shutil.rmtree(workspace)
    elif checkpoint.exists:
        saved = checkpoint.load(cfg.version, task.prompt)
        checkpoint.restore_workspace(saved)
    elif not checkpoint.exists and workspace.exists():
        # A failure during workspace setup happened before the first committed
        # loop state. There is nothing safe to resume, so rebuild from the task
        # fixture and rerun setup instead of trusting a partial workspace.
        shutil.rmtree(workspace)

    initialized = not workspace.exists()
    workspace.mkdir(parents=True, exist_ok=True)
    if initialized:
        if task.workspace_dir:
            shutil.copytree(task.workspace_dir, workspace, dirs_exist_ok=True)

    async with SANDBOXES[sandbox_kind](workspace) as sandbox:
        if initialized and task.setup:
            await sandbox.run(task.setup, timeout_s=120)

        trace = TraceWriter(
            out_dir / "traces",
            task_id=run_key,
            run_id=run_key,
            resume=resume and checkpoint.exists,
        )
        executor = ToolExecutor(
            sandbox,
            max_output_chars=cfg.policy("limits.max_output_chars", 8000),
        )
        loop = AgentLoop(
            cfg,
            LLMClient(),
            executor,
            trace,
            checkpoint=checkpoint,
            fault_exit_after_checkpoint=fault_exit_after_checkpoint,
        )
        result = await loop.run(task.prompt)

        # Ground truth: the check command, run after the agent is done.
        check = await sandbox.run(task.check, timeout_s=task.timeout_s)

    return TaskOutcome(
        task_id=task.task_id, repeat=repeat, run_id=result.run_id,
        passed=check.exit_code == 0, exit_reason=result.exit_reason,
        steps=result.steps, cost_usd=round(result.cost_usd, 4),
        tokens=result.tokens_in + result.tokens_out,
        harness_version=cfg.version,
        check_tail=(check.stdout + check.stderr)[-300:],
    )


async def run_suite(tasks_root: Path, out_dir: Path, repeats: int = 1,
                    concurrency: int = 2, task_ids: list[str] | None = None,
                    sandbox_kind: str = "docker", harness_dir: Path | None = None,
                    resume: bool = False,
                    fault_exit_after_checkpoint: int | None = None) -> dict:
    cfg = HarnessConfig.load(harness_dir) if harness_dir else HarnessConfig.load()
    tasks = discover_tasks(tasks_root)
    if task_ids:
        tasks = [t for t in tasks if t.task_id in task_ids]
    if fault_exit_after_checkpoint is not None:
        if fault_exit_after_checkpoint < 0:
            raise ValueError("fault checkpoint step must be >= 0")
        if concurrency != 1 or len(tasks) * repeats != 1:
            raise ValueError(
                "fault injection requires exactly one task/repeat and concurrency=1"
            )
    out_dir.mkdir(parents=True, exist_ok=True)

    # Crash-safe: every outcome hits results.jsonl the moment it exists; --resume
    # skips completed (task, repeat) pairs and re-runs infra failures.
    sink = ResultSink(out_dir, resume=resume)
    sink.check_harness_version(cfg.version)
    if sink.n_resumed:
        print(f"[runner] resume: {sink.n_resumed} completed outcomes kept, "
              f"skipping them", flush=True)

    RunManifest(
        benchmark="native-suite",
        harness_version=cfg.version,
        agent_model=os.environ.get("AGENT_MODEL", "claude-haiku-4-5-20251001"),
        miner_model=os.environ.get("MINER_MODEL", "claude-sonnet-5"),
        suite_hash=suite_hash([t.task_id for t in tasks]),
        task_ids=[t.task_id for t in tasks],
        repeats=repeats, max_steps=cfg.policy("limits.max_steps", 30),
        temperature=configured_temperature(),
        source_revision=repository_revision(Path(__file__).parents[3]),
        source_dirty=repository_is_dirty(Path(__file__).parents[3]),
        suite_content_hash=tree_hash(
            [tasks_root / t.task_id for t in tasks], tasks_root
        ),
        pricing_revision=pricing_revision(),
        extra={"sandbox": sandbox_kind,
               "harness_dir": str(harness_dir) if harness_dir else "harness/"},
    ).write(out_dir)

    sem = asyncio.Semaphore(concurrency)

    async def guarded(task: Task, r: int) -> None:
        async with sem:
            # Infrastructure failures (network, sandbox) must not kill the suite,
            # and must not silently masquerade as agent failures: retry the whole
            # task once, then record an explicit api_error outcome.
            for attempt in (1, 2):
                try:
                    run_kwargs = {"resume": resume or attempt > 1}
                    if fault_exit_after_checkpoint is not None:
                        run_kwargs["fault_exit_after_checkpoint"] = (
                            fault_exit_after_checkpoint
                        )
                    sink.record(await run_one(
                        task, cfg, out_dir, r, sandbox_kind, **run_kwargs
                    ))
                    return
                except UnretryableLLMError as e:
                    print(f"[runner] {task.task_id} r{r} unretryable API failure: "
                          f"{str(e)[:150]}", flush=True)
                    break
                except Exception as e:
                    print(f"[runner] {task.task_id} r{r} infra failure "
                          f"(attempt {attempt}/2): {type(e).__name__}: {str(e)[:150]}",
                          flush=True)
            sink.record(TaskOutcome(
                task_id=task.task_id, repeat=r, run_id=f"{task.task_id}-r{r}-infra-fail",
                passed=False, exit_reason="api_error", steps=0, cost_usd=0.0,
                tokens=0, harness_version=cfg.version, check_tail="infra failure"))

    jobs = [(t, r) for t in tasks for r in range(repeats)
            if not sink.is_done(t.task_id, r)]
    await asyncio.gather(*(guarded(t, r) for t, r in jobs))

    outcomes = [TaskOutcome(**row) for row in sink.rows()]
    summary = {
        "harness_version": cfg.version,
        "n_tasks": len(tasks),
        "repeats": repeats,
        "pass_rate": round(sum(o.passed for o in outcomes) / max(len(outcomes), 1), 3),
        "total_cost_usd": round(sum(o.cost_usd for o in outcomes), 2),
        "exit_reasons": dict(Counter(o.exit_reason for o in outcomes)),
        "per_task": {
            t.task_id: [o.passed for o in outcomes if o.task_id == t.task_id] for t in tasks
        },
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", type=Path, default=Path("tasks"))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--task-ids", nargs="*", default=None)
    ap.add_argument("--sandbox", choices=list(SANDBOXES), default="docker")
    ap.add_argument("--harness-dir", type=Path, default=None,
                    help="Use an alternate harness component dir (for A/B comparisons)")
    ap.add_argument("--resume", action="store_true",
                    help="Continue a crashed run: keep completed outcomes in --out, "
                         "re-run only missing (task, repeat) pairs and infra failures")
    ap.add_argument(
        "--fault-exit-after-checkpoint",
        type=int,
        metavar="STEP",
        help="test-only: exit process with code 86 after committing STEP "
             "(requires one task/repeat and concurrency=1)",
    )
    args = ap.parse_args()
    summary = asyncio.run(run_suite(args.tasks, args.out, args.repeats,
                                    args.concurrency, args.task_ids, args.sandbox,
                                    args.harness_dir, resume=args.resume,
                                    fault_exit_after_checkpoint=(
                                        args.fault_exit_after_checkpoint
                                    )))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
