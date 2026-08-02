"""Durable episode checkpoints for the agent loop.

The checkpoint is the committed state at an agent-turn boundary: messages,
episode memory, termination guards, and the next model-call index. Writes use
write-then-replace so a process crash cannot leave a partially-written JSON file.

This is intentionally a local-file backend first. The schema and store boundary
let a future SQLite/Postgres implementation preserve the same loop contract.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .loop import TaskResult

SCHEMA_VERSION = 2


def prompt_fingerprint(prompt: str) -> str:
    return hashlib.sha256(prompt.encode()).hexdigest()[:16]


@dataclass
class AgentCheckpoint:
    harness_version: str
    task_prompt_hash: str
    next_step: int
    messages: list[dict[str, Any]]
    tests_ran: bool = False
    recent_actions: list[str] = field(default_factory=list)
    consecutive_validation_errors: int = 0
    memory_notes: dict[str, str] = field(default_factory=dict)
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    workspace_snapshot: str | None = None
    parent_run: str | None = None
    parent_harness_version: str | None = None
    final_result: dict[str, Any] | None = None
    schema_version: int = SCHEMA_VERSION


class CheckpointMismatchError(ValueError):
    """The saved episode belongs to a different prompt or harness revision."""


@dataclass(frozen=True)
class CheckpointWrite:
    duration_s: float
    snapshot_files: int
    snapshot_bytes: int


class AgentCheckpointStore:
    def __init__(self, path: Path, workspace: Path | None = None,
                 snapshots_dir: Path | None = None, history_dir: Path | None = None):
        self.path = Path(path)
        self.workspace = Path(workspace) if workspace else None
        self.snapshots_dir = Path(snapshots_dir) if snapshots_dir else None
        self.history_dir = Path(history_dir) if history_dir else None
        self._record: AgentCheckpoint | None = None

    @property
    def exists(self) -> bool:
        return self.path.exists()

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)
        self.path.with_suffix(self.path.suffix + ".tmp").unlink(missing_ok=True)
        if self.snapshots_dir and self.snapshots_dir.exists():
            shutil.rmtree(self.snapshots_dir)
        if self.history_dir and self.history_dir.exists():
            shutil.rmtree(self.history_dir)
        self._record = None

    def load(self, harness_version: str, task_prompt: str) -> AgentCheckpoint | None:
        if not self.path.exists():
            return None
        data = json.loads(self.path.read_text(encoding="utf-8"))
        record = AgentCheckpoint(**data)
        if record.schema_version != SCHEMA_VERSION:
            raise CheckpointMismatchError(
                f"checkpoint schema {record.schema_version} != runtime {SCHEMA_VERSION}"
            )
        expected_prompt = prompt_fingerprint(task_prompt)
        if record.harness_version != harness_version:
            raise CheckpointMismatchError(
                f"checkpoint harness {record.harness_version} != current {harness_version}"
            )
        if record.task_prompt_hash != expected_prompt:
            raise CheckpointMismatchError(
                f"checkpoint prompt {record.task_prompt_hash} != current {expected_prompt}"
            )
        self._record = record
        return record

    @staticmethod
    def read(path: Path) -> AgentCheckpoint:
        return AgentCheckpoint(**json.loads(Path(path).read_text(encoding="utf-8")))

    @staticmethod
    def _write_atomic(path: Path, payload: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)

    def _snapshot_workspace(self, record: AgentCheckpoint) -> tuple[int, int]:
        if self.workspace is None or self.snapshots_dir is None:
            return (0, 0)
        if not self.workspace.exists():
            raise FileNotFoundError(f"checkpoint workspace missing: {self.workspace}")

        name = f"step-{record.next_step:04d}"
        target = self.snapshots_dir / name
        # Completing an already-checkpointed turn does not need another copy.
        if record.workspace_snapshot == name and target.exists():
            return self._snapshot_size(target)

        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        pending = self.snapshots_dir / f".{name}.{os.getpid()}.tmp"
        if pending.exists():
            shutil.rmtree(pending)
        shutil.copytree(self.workspace, pending)
        if target.exists():
            shutil.rmtree(target)
        os.replace(pending, target)
        record.workspace_snapshot = name
        return self._snapshot_size(target)

    @staticmethod
    def _snapshot_size(root: Path) -> tuple[int, int]:
        files = [path for path in root.rglob("*") if path.is_file()]
        return len(files), sum(path.stat().st_size for path in files)

    def save(self, record: AgentCheckpoint) -> CheckpointWrite:
        started = time.monotonic()
        snapshot_files, snapshot_bytes = self._snapshot_workspace(record)
        payload = json.dumps(asdict(record), ensure_ascii=False, separators=(",", ":"))
        self._write_atomic(self.path, payload)
        if self.history_dir:
            self._write_atomic(
                self.history_dir / f"step-{record.next_step:04d}.json", payload
            )
        self._record = record
        return CheckpointWrite(
            duration_s=time.monotonic() - started,
            snapshot_files=snapshot_files,
            snapshot_bytes=snapshot_bytes,
        )

    def restore_workspace(self, record: AgentCheckpoint | None = None) -> None:
        record = record or self._record
        if record is None:
            raise RuntimeError("load a checkpoint before restoring its workspace")
        if self.workspace is None or self.snapshots_dir is None:
            raise RuntimeError("checkpoint store has no workspace snapshot configuration")
        if not record.workspace_snapshot:
            raise RuntimeError("checkpoint does not reference a workspace snapshot")
        source = self.snapshots_dir / record.workspace_snapshot
        if not source.exists():
            raise FileNotFoundError(f"workspace snapshot missing: {source}")
        if self.workspace.exists():
            shutil.rmtree(self.workspace)
        shutil.copytree(source, self.workspace)

    def complete(
        self,
        result: TaskResult,
        record: AgentCheckpoint | None = None,
    ) -> CheckpointWrite:
        record = record or self._record
        if record is None:
            raise RuntimeError("cannot complete an episode before its first checkpoint")
        record.final_result = asdict(result)
        return self.save(record)

    @staticmethod
    def restored_result(record: AgentCheckpoint) -> TaskResult | None:
        from .loop import TaskResult

        return TaskResult(**record.final_result) if record.final_result else None
