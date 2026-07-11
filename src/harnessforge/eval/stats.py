"""Statistics helpers for reporting eval results honestly.

Two things every result in this project should carry:
1. A confidence interval — single-run pass rates on borderline tasks are noise
   (this project has the scars to prove it; see EXPERIMENTS.md).
2. A run manifest — model, temperature, harness version, suite hash, seed — so
   any number can be reproduced and attributed to an exact configuration.
"""

from __future__ import annotations

import hashlib
import json
import platform
import random
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion (better than normal approx
    for small n and extreme rates). Returns (low, high) at ~95% by default."""
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def paired_bootstrap_delta(before: dict[str, list[bool]], after: dict[str, list[bool]],
                           n_boot: int = 10000, seed: int = 0) -> dict[str, float]:
    """Bootstrap the paired per-task pass-rate delta (after - before).

    before/after map task_id -> list of pass/fail across repeats. Resamples tasks
    with replacement; within a task, averages the available repeats. Returns the
    mean delta and a 95% CI. If the CI crosses zero, the change is not supported.
    """
    tasks = [t for t in before if t in after]
    if not tasks:
        return {"mean_delta": 0.0, "ci_low": 0.0, "ci_high": 0.0, "n_tasks": 0}

    def rate(d: dict[str, list[bool]], t: str) -> float:
        vals = d[t]
        return sum(vals) / len(vals) if vals else 0.0

    per_task_delta = {t: rate(after, t) - rate(before, t) for t in tasks}
    observed = sum(per_task_delta.values()) / len(tasks)

    rng = random.Random(seed)
    boots = []
    for _ in range(n_boot):
        sample = [per_task_delta[rng.choice(tasks)] for _ in tasks]
        boots.append(sum(sample) / len(sample))
    boots.sort()
    return {
        "mean_delta": round(observed, 4),
        "ci_low": round(boots[int(0.025 * n_boot)], 4),
        "ci_high": round(boots[int(0.975 * n_boot)], 4),
        "n_tasks": len(tasks),
    }


def suite_hash(task_ids: list[str]) -> str:
    return hashlib.sha256("\x00".join(sorted(task_ids)).encode()).hexdigest()[:12]


@dataclass
class RunManifest:
    benchmark: str
    harness_version: str
    agent_model: str
    miner_model: str
    suite_hash: str
    task_ids: list[str]
    repeats: int
    max_steps: int
    seed: int = 0
    started_at: float = field(default_factory=time.time)
    platform: str = field(default_factory=lambda: platform.platform())
    extra: dict[str, Any] = field(default_factory=dict)

    def write(self, out_dir: Path) -> None:
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        (Path(out_dir) / "manifest.json").write_text(
            json.dumps(asdict(self), indent=2), encoding="utf-8")
