"""Eval task format (terminal-bench style).

A task is a directory:
    tasks/<task_id>/
        task.yaml        # prompt, setup, check command, tags
        workspace/       # initial files copied into the sandbox workspace
        (anything the check command needs, e.g. hidden tests)

task.yaml:
    prompt: |
      Fix the failing test in calc.py.
    setup: "pip install -q pytest"       # optional, runs before the agent starts
    check: "pytest tests/ -q"            # exit 0 == task passed (run AFTER the agent)
    tags: [bugfix, python]
    timeout_s: 300
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Task:
    task_id: str
    prompt: str
    check: str
    setup: str | None = None
    tags: list[str] = field(default_factory=list)
    timeout_s: int = 300
    workspace_dir: Path | None = None

    @classmethod
    def load(cls, task_dir: Path) -> "Task":
        task_dir = Path(task_dir)
        meta = yaml.safe_load((task_dir / "task.yaml").read_text(encoding="utf-8"))
        ws = task_dir / "workspace"
        return cls(
            task_id=task_dir.name,
            prompt=meta["prompt"],
            check=meta["check"],
            setup=meta.get("setup"),
            tags=meta.get("tags", []),
            timeout_s=meta.get("timeout_s", 300),
            workspace_dir=ws if ws.exists() else None,
        )


def discover_tasks(tasks_root: Path) -> list[Task]:
    return sorted(
        (Task.load(d) for d in Path(tasks_root).iterdir() if (d / "task.yaml").exists()),
        key=lambda t: t.task_id,
    )
