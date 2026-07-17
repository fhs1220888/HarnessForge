"""Crash-safe result persistence + resume for the eval runners.

Motivation (a failure we actually hit — see EXPERIMENTS.md): a suite run is
40+ agent runs of real API spend, and both runners used to buffer outcomes in
memory and write results.jsonl once at the end — any mid-suite crash threw away
every *completed* result. ResultSink inverts that: each outcome is appended to
results.jsonl the moment it exists, and `--resume` picks up where a crashed run
left off.

Resume semantics:
- completed (task_id, repeat) pairs are skipped, their rows kept
- infra-failure rows (api_error/infra_error) are dropped and re-run — they are
  retriable by definition, and keeping them would double-count after the redo
- mixing harness versions in one results file is refused: a resumed run must
  use the same harness the original measured, or provenance is corrupted
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

INFRA_EXIT_REASONS = ("api_error", "infra_error")


class ResultSink:
    def __init__(self, out_dir: Path, resume: bool = False):
        out_dir.mkdir(parents=True, exist_ok=True)
        self.path = out_dir / "results.jsonl"
        self._rows: list[dict[str, Any]] = []
        self.n_resumed = 0

        if resume and self.path.exists():
            kept = []
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                if row.get("exit_reason") in INFRA_EXIT_REASONS:
                    continue  # retriable; will be re-run, so drop the stale row
                kept.append(row)
            self._rows = kept
            self.n_resumed = len(kept)
            with self.path.open("w", encoding="utf-8") as f:  # compact: kept rows only
                for row in kept:
                    f.write(json.dumps(row) + "\n")
        else:
            self.path.write_text("", encoding="utf-8")  # fresh run truncates

    def check_harness_version(self, current_version: str) -> None:
        """Refuse to mix results from different harness versions in one file."""
        stale = {r["harness_version"] for r in self._rows} - {current_version}
        if stale:
            raise ValueError(
                f"resume refused: {self.path} contains outcomes from harness "
                f"version(s) {sorted(stale)} but the current harness is "
                f"{current_version}. Resume with the same harness, or start a "
                f"fresh --out dir.")

    def is_done(self, task_id: str, repeat: int) -> bool:
        return any(r["task_id"] == task_id and r["repeat"] == repeat for r in self._rows)

    def record(self, outcome: Any) -> None:
        """Append one outcome (a dataclass) to results.jsonl immediately."""
        row = asdict(outcome)
        self._rows.append(row)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")

    def rows(self) -> list[dict[str, Any]]:
        return list(self._rows)
