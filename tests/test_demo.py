from __future__ import annotations

import json
from pathlib import Path

import pytest

from harnessforge.demo import DEFAULT_DATA, render_demo, verified_scorecard


def test_offline_demo_verifies_and_renders_checked_evidence():
    scorecard = verified_scorecard()
    rendered = render_demo(scorecard)

    assert "No API key, network, or Docker required" in rendered
    assert "11/16 = 68.8%" in rendered
    assert "not an official full-suite score" in rendered
    assert "2 calls / 2,845 tokens" in rendered
    assert "DECISION REJECT" in rendered
    assert "Scorecard integrity: VERIFIED" in rendered


def test_offline_demo_rejects_scorecard_drift(tmp_path):
    for source in DEFAULT_DATA.glob("*.json"):
        tmp_path.joinpath(source.name).write_bytes(source.read_bytes())
    scorecard_path = tmp_path / "benchmark_scorecard.json"
    scorecard = json.loads(scorecard_path.read_text(encoding="utf-8"))
    scorecard["capability_external"]["outcomes"]["rate"] = 1.0
    scorecard_path.write_text(json.dumps(scorecard), encoding="utf-8")

    with pytest.raises(RuntimeError, match="drifted"):
        verified_scorecard(tmp_path)


def test_pages_dashboard_reads_generated_evidence_without_placeholder_intervals():
    index = Path(__file__).parents[1].joinpath("docs/index.html").read_text(encoding="utf-8")

    assert "benchmark_scorecard.json" in index
    assert "tb_holdout_v1_verifier_scorecard.json" in index
    assert "tb_selfverify_comparison.json" in index
    assert "verification_candidate_comparison.json" in index
    assert "−…" not in index
