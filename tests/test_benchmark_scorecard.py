"""The checked-in benchmark scorecard must reproduce from its evidence inputs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harnessforge.eval.benchmark_scorecard import build_scorecard

DATA = Path(__file__).parents[1] / "docs/data"


def _read(name: str) -> dict:
    return json.loads(DATA.joinpath(name).read_text(encoding="utf-8"))


def test_checked_scorecard_reproduces_from_evidence():
    generated = build_scorecard(
        _read("tb_baseline_summary.json"),
        _read("tb_selfverify_comparison.json"),
        _read("durable_recovery_t01.json"),
        _read("durable_counterfactual_multitask.json"),
        _read("verification_candidate_comparison.json"),
    )

    assert generated == _read("benchmark_scorecard.json")


def test_scorecard_rejects_inconsistent_external_denominator():
    baseline = _read("tb_baseline_summary.json")
    baseline["n_scored"] += 1

    with pytest.raises(ValueError, match="scored count"):
        build_scorecard(
            baseline,
            _read("tb_selfverify_comparison.json"),
            _read("durable_recovery_t01.json"),
            _read("durable_counterfactual_multitask.json"),
            _read("verification_candidate_comparison.json"),
        )
