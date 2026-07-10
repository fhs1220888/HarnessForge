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
import shutil
import tempfile
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from ..agent.llm import LLMClient
from ..agent.loop import AgentLoop
from ..agent.tools import ToolExecutor
from ..config import HarnessConfig
from ..sandbox.docker_sandbox import Sandbox
from ..sandbox.local_sandbox import LocalSandbox
from ..trace import TraceWriter
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
                  sandbox_kind: str = "docker") -> TaskOutcome:
    with tempfile.TemporaryDirectory(prefix=f"hforge-{task.task_id}-") as tmp:
        workspace = Path(tmp)
        if task.workspace_dir:
            shutil.copytree(task.workspace_dir, workspace, dirs_exist_ok=True)

        async with SANDBOXES[sandbox_kind](workspace) as sandbox:
            if task.setup:
                await sandbox.run(task.setup, timeout_s=120)

            trace = TraceWriter(out_dir / "traces", task_id=f"{task.task_id}-r{repeat}")
            executor = ToolExecutor(sandbox,
                                    max_output_chars=cfg.policy("limits.max_output_chars", 8000))
            loop = AgentLoop(cfg, LLMClient(), executor, trace)
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
                    sandbox_kind: str = "docker", harness_dir: Path | None = None) -> dict:
    cfg = HarnessConfig.load(harness_dir) if harness_dir else HarnessConfig.load()
    tasks = discover_tasks(tasks_root)
    if task_ids:
        tasks = [t for t in tasks if t.task_id in task_ids]
    out_dir.mkdir(parents=True, exist_ok=True)

    sem = asyncio.Semaphore(concurrency)
    outcomes: list[TaskOutcome] = []

    async def guarded(task: Task, r: int) -> None:
        async with sem:
            # Infrastructure failures (network, sandbox) must not kill the suite,
            # and must not silently masquerade as agent failures: retry the whole
            # task once, then record an explicit api_error outcome.
            for attempt in (1, 2):
                try:
                    outcomes.append(await run_one(task, cfg, out_dir, r, sandbox_kind))
                    return
                except Exception as e:
                    print(f"[runner] {task.task_id} r{r} infra failure "
                          f"(attempt {attempt}/2): {type(e).__name__}: {str(e)[:150]}",
                          flush=True)
            outcomes.append(TaskOutcome(
                task_id=task.task_id, repeat=r, run_id=f"{task.task_id}-r{r}-infra-fail",
                passed=False, exit_reason="api_error", steps=0, cost_usd=0.0,
                tokens=0, harness_version=cfg.version, check_tail="infra failure"))

    await asyncio.gather(*(guarded(t, r) for t in tasks for r in range(repeats)))

    with (out_dir / "results.jsonl").open("w", encoding="utf-8") as f:
        for o in outcomes:
            f.write(json.dumps(asdict(o)) + "\n")

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
    args = ap.parse_args()
    summary = asyncio.run(run_suite(args.tasks, args.out, args.repeats,
                                    args.concurrency, args.task_ids, args.sandbox,
                                    args.harness_dir))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
