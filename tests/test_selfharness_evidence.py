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
        "campaign_report": _read(DATA / "selfharness_campaign_v2_report.json"),
    }
    inputs.update(overrides)
    return build_selfharness_scorecard(**inputs)


def test_checked_selfharness_scorecard_reproduces_from_evidence():
    assert _build() == _read(DATA / "selfharness_scorecard.json")


def test_current_evidence_confirms_efficiency_and_autonomy_not_pass_rate():
    scorecard = _build()

    assert scorecard["closed_loop_execution"]["search_rounds_with_candidate_evidence"] == 3
    assert scorecard["closed_loop_execution"]["candidates_evaluated"] == 6
    assert scorecard["confirmed_self_improvement"]["confirmed"] is True
    assert scorecard["confirmed_self_improvement"]["pass_rate_improvement_confirmed"] is False
    assert scorecard["claim_status"]["multi_round_unattended_execution"]["confirmed"] is True
    assert scorecard["claim_status"]["multi_round_unattended_improvement"]["confirmed"] is False
    assert scorecard["claim_status"]["holdout_68_75_is_causal_uplift"]["confirmed"] is False


def test_completed_campaign_snapshot_has_consistent_candidate_and_lineage_counts():
    campaign = _read(DATA / "selfharness_campaign_v2_report.json")
    audit = _read(DATA / "selfharness_campaign_v2_scorecard.json")
    rounds = campaign["round_reports"]

    assert campaign["status"] == "completed"
    assert len(rounds) == campaign["rounds_completed"] == 3
    assert campaign["autonomous_round_transitions"] == 2
    assert sum(row["n_candidates"] for row in rounds) == audit["campaign"][
        "candidate_gates"
    ] == 6
    assert sum(row["n_winners"] for row in rounds) == audit["campaign"][
        "promoted"
    ] == 1
    assert campaign["pass_rate_trajectory"] == audit["campaign"][
        "pass_rate_trajectory"
    ]
    assert rounds[0]["baseline"]["harness_version"] == "cd2d29eae108"
    assert rounds[-1]["final"]["harness_version"] == "a6a55ef4f4bf"


def test_scorecard_refuses_to_keep_efficiency_claim_if_interval_crosses_zero():
    comparison = _read(DATA / "tb_selfverify_comparison.json")
    comparison["steps"]["ci_high"] = 0.1

    with pytest.raises(ValueError, match="step-efficiency claim"):
        _build(external_comparison=comparison)


def test_completed_three_round_audit_confirms_execution_not_improvement():
    round_reports = [
        {
            "baseline": {"harness_version": f"round{index - 1}", "pass_rate": 0.5},
            "final": {"harness_version": f"round{index}", "pass_rate": 0.6},
            "n_candidates": 1,
            "n_winners": 1,
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

    scorecard = _build(campaign_report=campaign)

    assert scorecard["claim_status"]["multi_round_unattended_execution"]["confirmed"] is True
    assert scorecard["claim_status"]["multi_round_unattended_improvement"]["confirmed"] is False
    assert scorecard["claim_status"]["self_harness_improves_overall_pass_rate"]["confirmed"] is False


def test_completed_campaign_and_matched_causal_proof_upgrade_both_claims():
    round_reports = [
        {
            "baseline": {
                "harness_version": f"round{index - 1}",
                "pass_rate": 0.5,
            },
            "final": {"harness_version": f"round{index}", "pass_rate": 0.6},
            "n_candidates": 1,
            "n_winners": 1,
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
