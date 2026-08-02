"""Fork a native agent episode from a committed historical checkpoint.

The fork gets its own workspace, checkpoint history, and trace. It may bind to a
different harness revision, enabling counterfactual continuation from the same
messages, budget ledger, and filesystem state.

Usage:
    python -m harnessforge.eval.fork \
        --source-run runs/control --target-run runs/candidate \
        --task-id t01_fix_off_by_one --step 3 \
        --harness-dir harness_candidate
"""

from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

from ..agent.checkpoint import AgentCheckpointStore, SCHEMA_VERSION
from ..config import HarnessConfig
from ..trace import EventType, TraceWriter


@dataclass(frozen=True)
class ForkResult:
    source_run: str
    target_run: str
    run_key: str
    checkpoint_step: int
    parent_harness_version: str
    target_harness_version: str
    prefix_tokens: int
    prefix_cost_usd: float
    workspace_snapshot: str


def fork_native_run(source_run: Path, target_run: Path, task_id: str,
                    harness_dir: Path, repeat: int = 0,
                    step: int | None = None) -> ForkResult:
    source_run = Path(source_run).resolve()
    target_run = Path(target_run).resolve()
    if source_run == target_run:
        raise ValueError("source and target run directories must differ")

    run_key = f"{task_id}-r{repeat}"
    if step is None:
        source_checkpoint = source_run / "checkpoints" / f"{run_key}.json"
    else:
        source_checkpoint = (
            source_run / "checkpoint_history" / run_key / f"step-{step:04d}.json"
        )
    if not source_checkpoint.exists():
        raise FileNotFoundError(f"source checkpoint not found: {source_checkpoint}")

    record = AgentCheckpointStore.read(source_checkpoint)
    if record.schema_version != SCHEMA_VERSION:
        raise ValueError(
            f"checkpoint schema {record.schema_version} != runtime {SCHEMA_VERSION}"
        )
    if not record.workspace_snapshot:
        raise ValueError("source checkpoint has no workspace snapshot")
    source_snapshot = (
        source_run / "workspace_snapshots" / run_key / record.workspace_snapshot
    )
    if not source_snapshot.exists():
        raise FileNotFoundError(f"source workspace snapshot not found: {source_snapshot}")

    target_checkpoint_path = target_run / "checkpoints" / f"{run_key}.json"
    target_workspace = target_run / "workspaces" / run_key
    if target_checkpoint_path.exists() or target_workspace.exists():
        raise FileExistsError(
            f"target already contains fork state for {run_key}: {target_run}"
        )

    target_cfg = HarnessConfig.load(harness_dir)
    parent_harness = record.harness_version
    record.parent_run = f"{source_run}:{run_key}"
    record.parent_harness_version = parent_harness
    record.harness_version = target_cfg.version
    record.final_result = None
    record.workspace_snapshot = None

    target_workspace.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_snapshot, target_workspace)
    target_store = AgentCheckpointStore(
        target_checkpoint_path,
        workspace=target_workspace,
        snapshots_dir=target_run / "workspace_snapshots" / run_key,
        history_dir=target_run / "checkpoint_history" / run_key,
    )
    target_store.save(record)

    trace = TraceWriter(
        target_run / "traces", task_id=run_key, run_id=run_key, resume=False
    )
    trace.emit(EventType.RUN_START, {
        "harness_version": target_cfg.version,
        "model": "continued-by-runner",
        "forked": True,
    })
    trace.emit(EventType.FORK, {
        "parent_run": record.parent_run,
        "parent_checkpoint": str(source_checkpoint),
        "checkpoint_step": record.next_step,
        "parent_harness_version": parent_harness,
        "target_harness_version": target_cfg.version,
        "prefix_tokens_in": record.tokens_in,
        "prefix_tokens_out": record.tokens_out,
        "prefix_cost_usd": record.cost_usd,
    })

    return ForkResult(
        source_run=str(source_run),
        target_run=str(target_run),
        run_key=run_key,
        checkpoint_step=record.next_step,
        parent_harness_version=parent_harness,
        target_harness_version=target_cfg.version,
        prefix_tokens=record.tokens_in + record.tokens_out,
        prefix_cost_usd=record.cost_usd,
        workspace_snapshot=record.workspace_snapshot or "",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-run", type=Path, required=True)
    parser.add_argument("--target-run", type=Path, required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--repeat", type=int, default=0)
    parser.add_argument("--step", type=int,
                        help="historical next-step checkpoint; default latest")
    parser.add_argument("--harness-dir", type=Path, default=Path("harness"))
    args = parser.parse_args()

    result = fork_native_run(
        args.source_run,
        args.target_run,
        args.task_id,
        args.harness_dir,
        repeat=args.repeat,
        step=args.step,
    )
    print(json.dumps(asdict(result), indent=2))
    print("\nContinue the fork with:")
    print(
        "python -m harnessforge.eval.runner "
        f"--tasks tasks --out {args.target_run} --task-ids {args.task_id} "
        f"--repeats {args.repeat + 1} --harness-dir {args.harness_dir} --resume"
    )


if __name__ == "__main__":
    main()
