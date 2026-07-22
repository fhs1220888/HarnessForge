"""Committed data snapshots and request-defined comparison constants."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .common import DATA


@lru_cache(maxsize=None)
def load_json(name: str) -> Any:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def baseline() -> dict[str, Any]:
    return load_json("tb_baseline_summary.json")


def finishfix() -> dict[str, Any]:
    return load_json("tb_finishfix_summary.json")


def selfverify() -> dict[str, Any]:
    return load_json("tb_selfverify_summary.json")


def calibration() -> list[dict[str, Any]]:
    return load_json("calibration.json")


TB_HARNESS_FIXABLE = {
    "prove-plus-comm",
    "crack-7z-hash",
    "openssl-selfsigned-cert",
    "polyglot-c-py",
    "merge-diff-arc-agi-task",
    "qemu-startup",
}

TB_CAPABILITY_LIMITED = {
    "mteb-leaderboard",
    "mteb-retrieve",
    "hf-model-inference",
    "raman-fitting",
}

TB_REGRESSION_GUARDS = {
    "code-from-image",
    "cobol-modernization",
    "constraints-scheduling",
}


SELFVERIFY_EFFECTS = {
    "pass_rate": {"delta": 0.067, "lo": -0.100, "hi": 0.267, "significant": False},
    # The source report records only that this interval crosses zero.
    "cost_per_run": {"delta": -0.013, "lo": None, "hi": None, "significant": False},
    "steps_per_run": {"delta": -0.069, "lo": -0.133, "hi": -0.016, "significant": True},
}


VALIDATION_GROUPS = [
    {
        "label": "Targets",
        "control": 0.143,
        "treatment": 0.238,
        "delta": 0.095,
        "lo": -0.095,
        "hi": 0.333,
    },
    {
        "label": "All 10 tasks",
        "control": 0.367,
        "treatment": 0.433,
        "delta": 0.067,
        "lo": -0.100,
        "hi": 0.267,
    },
    {
        "label": "Regression guards",
        "control": 0.889,
        "treatment": 0.889,
        "delta": 0.0,
        "lo": None,
        "hi": None,
    },
]


def source_path(name: str) -> str:
    return str(Path("docs") / "data" / name)
