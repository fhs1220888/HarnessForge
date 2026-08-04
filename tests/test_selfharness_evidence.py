from __future__ import annotations

import json
from pathlib import Path

import pytest

from harnessforge.selfharness.evidence import build_selfharness_scorecard

ROOT = Path(__file__).parents[1]
DATA = ROOT / "docs" / "data"


def _read(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def _build(**overrides):
    inputs = {
        "round_report": _read(DATA / "selfharness_round1_report.json"),
        "round_verdicts": [
            _read(DATA / "selfharness_round1_verdicts.json"),
            _read(DATA / "selfharness_round2_verdicts.json"),
        ],
        "external_comparison": _read(DATA / "tb_selfverify_comparison.json"),
        "holdout": _read(DATA / "tb_holdout_v1_verifier_scorecard.json"),
        "candidate_gate": _read(DATA / "verification_candidate_comparison.json"),
        "calibration": _read(DATA / "calibration.json"),
    }
    inputs.update(overrides)
    return build_selfharness_scorecard(**inputs)


def test_checked_selfharness_scorecard_reproduces_from_evidence():
    assert _build() == _read(DATA / "selfharness_scorecard.json")


def test_current_evidence_confirms_efficiency_not_pass_rate_or_autonomy():
    scorecard = _build()

    assert scorecard["closed_loop_execution"]["search_rounds_with_candidate_evidence"] == 2
    assert scorecard["closed_loop_execution"]["candidates_evaluated"] == 7
    assert scorecard["confirmed_self_improvement"]["confirmed"] is True
    assert scorecard["confirmed_self_improvement"]["pass_rate_improvement_confirmed"] is False
    assert scorecard["claim_status"]["multi_round_unattended_execution"]["confirmed"] is False
    assert scorecard["claim_status"]["multi_round_unattended_improvement"]["confirmed"] is False
    assert scorecard["claim_status"]["holdout_68_75_is_causal_uplift"]["confirmed"] is False


def test_scorecard_refuses_to_keep_efficiency_claim_if_interval_crosses_zero():
    comparison = _read(DATA / "tb_selfverify_comparison.json")
    comparison["steps"]["ci_high"] = 0.1

    with pytest.raises(ValueError, match="step-efficiency claim"):
        _build(external_comparison=comparison)


def test_completed_three_round_audit_confirms_execution_not_improvement():
    campaign = {
        "status": "completed",
        "rounds_completed": 3,
        "autonomous_round_transitions": 2,
        "protocol": {"rounds_planned": 3},
    }

    scorecard = _build(campaign_report=campaign)

    assert scorecard["claim_status"]["multi_round_unattended_execution"]["confirmed"] is True
    assert scorecard["claim_status"]["multi_round_unattended_improvement"]["confirmed"] is False
    assert scorecard["claim_status"]["self_harness_improves_overall_pass_rate"]["confirmed"] is False


def test_completed_campaign_and_matched_causal_proof_upgrade_both_claims():
    round_reports = [
        {
            "baseline": {"harness_version": "round0"},
            "final": {"harness_version": f"round{index}"},
        }
        for index in range(1, 4)
    ]
    campaign = {
        "status": "completed",
        "rounds_completed": 3,
        "autonomous_round_transitions": 2,
        "protocol": {"rounds_planned": 3},
        "round_reports": round_reports,
    }
    proof = {
        "protocol_match": True,
        "control": {"harness_version": "round0"},
        "treatment": {"harness_version": "round3"},
        "sample_requirements": {"met": True},
        "paired_effects": {"pass_rate": {"ci_low": 0.05}},
        "decision": {"confirmed_causal_pass_rate_uplift": True},
    }

    scorecard = _build(campaign_report=campaign, causal_proof=proof)

    assert scorecard["claim_status"]["multi_round_unattended_execution"]["confirmed"] is True
    assert scorecard["claim_status"]["multi_round_unattended_improvement"]["confirmed"] is True
    assert scorecard["claim_status"]["self_harness_improves_overall_pass_rate"]["confirmed"] is True
    assert scorecard["forbidden_until_new_live_evidence"] == [
        "The 68.75% holdout result is a causal uplift over the development baseline."
    ]
