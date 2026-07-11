"""Run the harness over a Terminal-Bench subset.

Same shape as eval/runner.py but uses TBSandbox + the TB reward check, and a
separate (larger) budget since TB tasks are much harder than the native suite.
The harness components (system_prompt, tool_descriptions, loop_policy) are shared
— that's the whole point: measure the same harness on an external benchmark.

Usage:
    python -m harnessforge.eval.tb_runner \\
        --tb-root ~/terminal-bench-2 --out runs/tb_baseline \\
        --repeats 2 --concurrency 2 --tb-max-steps 25
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from ..agent.llm import LLMClient
from ..agent.loop import AgentLoop
from ..agent.tools import ToolExecutor
from ..config import HarnessConfig
import os

from ..sandbox.tb_sandbox import TBSandbox
from ..trace import TraceWriter
from .stats import RunManifest, suite_hash
from .tb_adapter import TBTask, load_subset


@dataclass
class TBOutcome:
    task_id: str
    repeat: int
    run_id: str
    passed: bool
    exit_reason: str
    steps: int
    cost_usd: float
    tokens: int
    harness_version: str
    difficulty: str
    category: str


def _tb_budget_config(base: HarnessConfig, max_steps: int) -> HarnessConfig:
    """Clone the harness config with a TB-appropriate step budget, leaving all
    evolvable *content* untouched so we still measure the same harness."""
    policy = copy.deepcopy(base.loop_policy)
    policy.setdefault("limits", {})["max_steps"] = max_steps
    policy["limits"]["max_tokens_per_task"] = max(
        policy["limits"].get("max_tokens_per_task", 150_000), 500_000)
    policy["limits"]["max_cost_usd_per_task"] = max(
        policy["limits"].get("max_cost_usd_per_task", 0.25), 1.50)
    return HarnessConfig(
        system_prompt=base.system_prompt,
        tool_descriptions=base.tool_descriptions,
        loop_policy=policy,
        version=base.version,  # content-derived; budget override is not "the harness"
    )


async def run_tb_task(task: TBTask, cfg: HarnessConfig, out_dir: Path, repeat: int) -> TBOutcome:
    async with TBSandbox(task.docker_image, task.test_dir, task.memory_mb,
                         task.allow_internet) as sandbox:
        trace = TraceWriter(out_dir / "traces", task_id=f"{task.task_id}-r{repeat}")
        executor = ToolExecutor(sandbox,
                                max_output_chars=cfg.policy("limits.max_output_chars", 8000))
        loop = AgentLoop(cfg, LLMClient(), executor, trace)
        result = await loop.run(task.instruction)
        passed = await sandbox.run_reward_check(task.reward_check_command(),
                                                timeout_s=task.verifier_timeout_s)
    return TBOutcome(
        task_id=task.task_id, repeat=repeat, run_id=result.run_id, passed=passed,
        exit_reason=result.exit_reason, steps=result.steps,
        cost_usd=round(result.cost_usd, 4), tokens=result.tokens_in + result.tokens_out,
        harness_version=cfg.version, difficulty=task.difficulty, category=task.category,
    )


async def run_tb_suite(tb_root: Path, out_dir: Path, repeats: int = 1, concurrency: int = 2,
                       subset: list[str] | None = None, max_steps: int = 25,
                       harness_dir: Path | None = None) -> dict:
    base = HarnessConfig.load(harness_dir) if harness_dir else HarnessConfig.load()
    cfg = _tb_budget_config(base, max_steps)
    tasks = load_subset(tb_root, subset)
    out_dir.mkdir(parents=True, exist_ok=True)

    RunManifest(
        benchmark="terminal-bench-2 / tb-subset",
        harness_version=cfg.version,
        agent_model=os.environ.get("AGENT_MODEL", "claude-haiku-4-5-20251001"),
        miner_model=os.environ.get("MINER_MODEL", "claude-sonnet-5"),
        suite_hash=suite_hash([t.task_id for t in tasks]),
        task_ids=[t.task_id for t in tasks],
        repeats=repeats, max_steps=max_steps,
        extra={"harness_dir": str(harness_dir) if harness_dir else "harness/"},
    ).write(out_dir)

    sem = asyncio.Semaphore(concurrency)
    outcomes: list[TBOutcome] = []

    async def guarded(task: TBTask, r: int) -> None:
        async with sem:
            for attempt in (1, 2):
                try:
                    outcomes.append(await run_tb_task(task, cfg, out_dir, r))
                    return
                except Exception as e:
                    print(f"[tb] {task.task_id} r{r} infra failure "
                          f"(attempt {attempt}/2): {type(e).__name__}: {str(e)[:150]}",
                          flush=True)
            outcomes.append(TBOutcome(
                task_id=task.task_id, repeat=r, run_id=f"{task.task_id}-r{r}-infra-fail",
                passed=False, exit_reason="infra_error", steps=0, cost_usd=0.0, tokens=0,
                harness_version=cfg.version, difficulty=task.difficulty, category=task.category))

    await asyncio.gather(*(guarded(t, r) for t in tasks for r in range(repeats)))

    with (out_dir / "results.jsonl").open("w", encoding="utf-8") as f:
        for o in outcomes:
            f.write(json.dumps(asdict(o)) + "\n")

    scored = [o for o in outcomes if o.exit_reason != "infra_error"]
    summary = {
        "benchmark": "terminal-bench-2 / tb-subset",
        "harness_version": cfg.version,
        "tb_max_steps": max_steps,
        "n_tasks": len(tasks),
        "repeats": repeats,
        "n_scored": len(scored),
        "n_infra_error": len(outcomes) - len(scored),
        "pass_rate": round(sum(o.passed for o in scored) / max(len(scored), 1), 3),
        "total_cost_usd": round(sum(o.cost_usd for o in outcomes), 2),
        "exit_reasons": dict(Counter(o.exit_reason for o in outcomes)),
        "per_task": {t.task_id: [o.passed for o in scored if o.task_id == t.task_id]
                     for t in tasks},
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tb-root", type=Path, required=True,
                    help="Path to a clone of harbor-framework/terminal-bench-2")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--tb-max-steps", type=int, default=25)
    ap.add_argument("--subset", nargs="*", default=None, help="task IDs; default tb-subset-v1")
    ap.add_argument("--harness-dir", type=Path, default=None)
    args = ap.parse_args()
    summary = asyncio.run(run_tb_suite(
        args.tb_root, args.out, args.repeats, args.concurrency,
        args.subset, args.tb_max_steps, args.harness_dir))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
