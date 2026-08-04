"""Build a machine-verifiable evidence card for the self-harness loop.

The scorecard separates three questions that are easy to conflate:

1. Did autonomous search and gating execute?
2. Did a paired intervention improve a measured outcome?
3. Did the final harness causally improve pass rate on a disjoint holdout?

Only the second question currently has a confirmed positive answer, and only for
step efficiency.  Keeping those claim states explicit prevents an incomplete
campaign or a cross-protocol point estimate from becoming a resume claim.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ..eval.counterfactual import _write_json_atomic


def _read(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _ci_excludes_zero(effect: dict[str, Any], *, positive: bool) -> bool:
    if positive:
        return float(effect["ci_low"]) > 0
    return float(effect["ci_high"]) < 0


def build_selfharness_scorecard(
    round_report: dict[str, Any],
    round_verdicts: list[list[dict[str, Any]]],
    external_comparison: dict[str, Any],
    holdout: dict[str, Any],
    candidate_gate: dict[str, Any],
    calibration: list[dict[str, Any]],
    campaign_report: dict[str, Any] | None = None,
    causal_proof: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Summarize observed self-improvement evidence without upgrading claims."""
    nonempty_rounds = [verdicts for verdicts in round_verdicts if verdicts]
    verdicts = [verdict for rows in nonempty_rounds for verdict in rows]
    accepted = [verdict for verdict in verdicts if verdict["accepted"]]
    rejected = [verdict for verdict in verdicts if not verdict["accepted"]]
    if len(verdicts) != len(accepted) + len(rejected):
        raise ValueError("candidate verdict accounting is inconsistent")

    pass_effect = external_comparison["pass_rate"]
    step_effect = external_comparison["steps"]
    pass_rate_confirmed = _ci_excludes_zero(pass_effect, positive=True)
    step_efficiency_confirmed = _ci_excludes_zero(step_effect, positive=False)
    if not step_efficiency_confirmed:
        raise ValueError("checked evidence no longer confirms the step-efficiency claim")

    campaign_completed = bool(
        campaign_report
        and campaign_report.get("status") == "completed"
        and campaign_report.get("rounds_completed", 0)
        >= campaign_report.get("protocol", {}).get("rounds_planned", 1)
    )
    autonomous_transitions = (
        int(campaign_report.get("autonomous_round_transitions", 0))
        if campaign_report
        else 0
    )
    sustained_autonomy_confirmed = campaign_completed and autonomous_transitions >= 2
    completed_full_suite_rounds = (
        int(campaign_report["rounds_completed"]) if campaign_completed else 1
    )
    causal_gate_passed = bool(
        causal_proof
        and causal_proof.get("protocol_match")
        and causal_proof.get("sample_requirements", {}).get("met")
        and causal_proof.get("paired_effects", {})
        .get("pass_rate", {})
        .get("ci_low", 0)
        > 0
        and causal_proof.get("decision", {}).get(
            "confirmed_causal_pass_rate_uplift"
        )
    )
    campaign_lineage_match = False
    if causal_gate_passed and campaign_completed:
        campaign_rounds = campaign_report.get("round_reports", [])
        if campaign_rounds:
            campaign_lineage_match = (
                causal_proof.get("control", {}).get("harness_version")
                == campaign_rounds[0].get("baseline", {}).get("harness_version")
                and causal_proof.get("treatment", {}).get("harness_version")
                == campaign_rounds[-1].get("final", {}).get("harness_version")
            )
    self_harness_pass_uplift_confirmed = (
        sustained_autonomy_confirmed
        and causal_gate_passed
        and campaign_lineage_match
    )

    native_calibration = next(
        row for row in calibration if row["round"] == "native round 1"
    )
    paired_gate = candidate_gate["paired_analysis"]
    if (
        candidate_gate["verdict"]["quality_gain_confirmed"]
        or candidate_gate["verdict"]["efficiency_gain_confirmed"]
    ):
        raise ValueError("the checked candidate-gate case must remain rejected")

    return {
        "schema_version": 1,
        "scorecard": "HarnessForge self-harness evidence",
        "positioning": (
            "Evidence-gated self-improving coding-agent harness: trace mining -> "
            "candidate generation -> isolated paired evaluation -> promotion or rejection."
        ),
        "closed_loop_execution": {
            "search_rounds_with_candidate_evidence": len(nonempty_rounds),
            "candidates_evaluated": len(verdicts),
            "small_gate_acceptances": len(accepted),
            "rejections": len(rejected),
            "completed_full_suite_rounds": completed_full_suite_rounds,
            "observed_round1_pass_rate": {
                "baseline": round_report["baseline"]["pass_rate"],
                "final": round_report["final"]["pass_rate"],
                "winners": round_report["n_winners"],
            },
            "evidence_grade": "live-model-multi-round-candidate-gating-partial",
        },
        "confirmed_self_improvement": {
            "metric": "steps_per_run",
            "benchmark": "Terminal-Bench 2.0 high-signal paired subset",
            "tasks": external_comparison["n_shared_tasks"],
            "mean_step_delta": step_effect["mean_delta"],
            "step_delta_ci95": [step_effect["ci_low"], step_effect["ci_high"]],
            "percent_change": step_effect["pct_change"],
            "confirmed": step_efficiency_confirmed,
            "pass_rate_delta_same_runs": pass_effect,
            "pass_rate_improvement_confirmed": pass_rate_confirmed,
            "decision": (
                "Efficiency improved with a confidence interval excluding zero; "
                "pass-rate improvement remains unconfirmed."
            ),
            "evidence_grade": "external-benchmark-paired",
        },
        "noise_rejection_evidence": {
            "earlier_false_positive": {
                "predicted_pass_rate_delta": native_calibration["predicted"],
                "small_validation_delta": native_calibration["smallval"],
                "controlled_delta": native_calibration["controlled"],
                "final_decision": "reverted",
            },
            "same_prefix_candidate": {
                "observed_control_pass_rate": candidate_gate["control"]["outcomes"][
                    "rate"
                ],
                "observed_treatment_pass_rate": candidate_gate["treatment"][
                    "outcomes"
                ]["rate"],
                "paired_pass_rate_delta": paired_gate["pass_rate_delta"],
                "token_change_percent": paired_gate["continuation_token_delta"][
                    "pct_change"
                ],
                "cost_change_percent": paired_gate["continuation_cost_usd_delta"][
                    "pct_change"
                ],
                "decision": "reject",
            },
            "evidence_grade": "controlled-gate-behavior",
        },
        "claim_status": {
            "self_harness_improves_overall_pass_rate": {
                "confirmed": self_harness_pass_uplift_confirmed,
                "reason": (
                    "completed campaign lineage matches a protocol-locked final "
                    "comparison whose paired pass-rate interval excludes zero"
                    if self_harness_pass_uplift_confirmed
                    else "requires a completed multi-round campaign plus a matched "
                    "round-0/final comparison with sufficient sample and CI lower bound > 0"
                ),
            },
            "multi_round_unattended_execution": {
                "confirmed": sustained_autonomy_confirmed,
                "reason": (
                    "no completed audited campaign with at least two automatic "
                    "round transitions"
                    if not sustained_autonomy_confirmed
                    else "completed isolated campaign audit"
                ),
            },
            "multi_round_unattended_improvement": {
                "confirmed": self_harness_pass_uplift_confirmed,
                "reason": (
                    "autonomous campaign and matched causal final comparison are both confirmed"
                    if self_harness_pass_uplift_confirmed
                    else "campaign completion proves autonomous execution; a matched final "
                    "control/treatment holdout is still required to prove improvement"
                ),
            },
            "holdout_68_75_is_causal_uplift": {
                "confirmed": False,
                "observed_result": {
                    "passes": holdout["passed_runs"],
                    "runs": holdout["scored_runs"],
                    "pass_rate": holdout["pass_rate"],
                },
                "reason": (
                    "development baseline and holdout use different models, tasks, "
                    "budgets, and harness revisions"
                ),
            },
        },
        "causal_proof_protocol": {
            "campaign": {
                "minimum_rounds": 3,
                "automatic_transitions_required": 2,
                "repository_harness_isolated": True,
                "persistent_report_after_each_round": True,
                "resume_must_preserve_protocol": True,
            },
            "final_comparison": {
                "immutable_control": "round-0 parent harness",
                "treatment": "final promoted campaign harness",
                "same_model_tasks_budgets_and_repeats": True,
                "minimum_disjoint_holdout_tasks": 20,
                "minimum_repeats_per_arm": 2,
                "primary_metric": "paired task-level pass-rate delta",
                "success_rule": "95% interval lower bound > 0; no regression gate breach",
            },
        },
        "causal_proof_evidence": {
            "provided": causal_proof is not None,
            "causal_gate_passed": causal_gate_passed,
            "campaign_lineage_match": campaign_lineage_match,
        },
        "resume_safe_claims": [
            "Built and executed a two-round candidate search with seven live-model gates.",
            "Confirmed a 6.94% step reduction on an external paired benchmark.",
            "Rejected attractive small-sample gains when uncertainty or cost regressed.",
        ],
        "forbidden_until_new_live_evidence": (
            [
                "The 68.75% holdout result is a causal uplift over the development baseline."
            ]
            if self_harness_pass_uplift_confirmed
            else [
                "Self-harness significantly improves overall pass rate.",
                "Self-harness continuously improves for multiple unattended rounds.",
                "The 68.75% holdout result is a causal uplift over the development baseline.",
            ]
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--round-report",
        type=Path,
        default=Path("docs/data/selfharness_round1_report.json"),
    )
    parser.add_argument(
        "--round-verdicts",
        type=Path,
        nargs="+",
        default=[
            Path("docs/data/selfharness_round1_verdicts.json"),
            Path("docs/data/selfharness_round2_verdicts.json"),
        ],
    )
    parser.add_argument(
        "--external-comparison",
        type=Path,
        default=Path("docs/data/tb_selfverify_comparison.json"),
    )
    parser.add_argument(
        "--holdout",
        type=Path,
        default=Path("docs/data/tb_holdout_v1_verifier_scorecard.json"),
    )
    parser.add_argument(
        "--candidate-gate",
        type=Path,
        default=Path("docs/data/verification_candidate_comparison.json"),
    )
    parser.add_argument(
        "--calibration",
        type=Path,
        default=Path("docs/data/calibration.json"),
    )
    parser.add_argument("--campaign-report", type=Path)
    parser.add_argument("--causal-proof", type=Path)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("docs/data/selfharness_scorecard.json"),
    )
    args = parser.parse_args()
    scorecard = build_selfharness_scorecard(
        _read(args.round_report),
        [_read(path) for path in args.round_verdicts],
        _read(args.external_comparison),
        _read(args.holdout),
        _read(args.candidate_gate),
        _read(args.calibration),
        _read(args.campaign_report) if args.campaign_report else None,
        _read(args.causal_proof) if args.causal_proof else None,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(args.out, scorecard)
    print(json.dumps(scorecard, indent=2))


if __name__ == "__main__":
    main()
