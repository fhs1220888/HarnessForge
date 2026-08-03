"""Build a recruiter-readable, machine-verifiable benchmark scorecard.

No composite score is emitted: capability, efficiency, runtime durability, and
evaluation efficiency answer different questions and should keep their denominators
and caveats visible.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .counterfactual import _write_json_atomic
from .stats import wilson_interval


def _read(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _rate(successes: int, observations: int) -> dict[str, Any]:
    low, high = wilson_interval(successes, observations)
    return {
        "successes": successes,
        "observations": observations,
        "rate": round(successes / observations, 6) if observations else None,
        "wilson_ci95": [round(low, 6), round(high, 6)] if observations else None,
    }


def build_scorecard(
    tb_baseline: dict[str, Any],
    tb_holdout: dict[str, Any],
    tb_efficiency: dict[str, Any],
    recovery: dict[str, Any],
    prefix_benchmark: dict[str, Any],
    candidate_screen: dict[str, Any],
    context_pilot: dict[str, Any],
    holdout_forecast: dict[str, Any],
) -> dict[str, Any]:
    scored = sum(len(values) for values in tb_baseline["per_task"].values())
    passes = sum(sum(bool(value) for value in values)
                 for values in tb_baseline["per_task"].values())
    if scored != tb_baseline["n_scored"]:
        raise ValueError("Terminal-Bench scored count does not match per-task outcomes")
    if round(passes / scored, 6) != tb_baseline["pass_rate"]:
        raise ValueError("Terminal-Bench pass rate does not match per-task outcomes")

    holdout_outcomes = [
        value
        for values in tb_holdout["per_task"].values()
        for value in values
    ]
    holdout_scored = len(holdout_outcomes)
    holdout_passes = sum(bool(value) for value in holdout_outcomes)
    if holdout_scored != tb_holdout["scored_runs"]:
        raise ValueError("Terminal-Bench holdout count does not match per-task outcomes")
    if holdout_passes != tb_holdout["passed_runs"]:
        raise ValueError("Terminal-Bench holdout passes do not match per-task outcomes")
    if round(holdout_passes / holdout_scored, 4) != tb_holdout["pass_rate"]:
        raise ValueError("Terminal-Bench holdout rate does not match per-task outcomes")

    infra_errors = int(tb_baseline["n_infra_error"])
    max_steps = int(tb_baseline["exit_reasons"].get("max_steps", 0))
    prefix = prefix_benchmark["aggregate"]
    screen = candidate_screen["paired_analysis"]
    if context_pilot["status"] != "infra_aborted_unscored":
        raise ValueError("Context pilot must remain explicitly unscored")
    if context_pilot["scored_runs"] != 0 or context_pilot["reward"] is not None:
        raise ValueError("Context pilot cannot carry a benchmark outcome")
    if holdout_forecast["status"] != "forecast_unscored":
        raise ValueError("Holdout forecast must remain explicitly unscored")
    if holdout_forecast["source_observation"]["passed_runs"] != holdout_passes:
        raise ValueError("Holdout forecast source passes do not match holdout evidence")
    if holdout_forecast["source_observation"]["scored_runs"] != holdout_scored:
        raise ValueError("Holdout forecast source count does not match holdout evidence")

    return {
        "schema_version": 2,
        "scorecard": "HarnessForge benchmark evidence",
        "composite_score": None,
        "composite_score_policy": (
            "Intentionally omitted: capability, efficiency, durability, and evaluation "
            "cost have different denominators and failure consequences."
        ),
        "capability_external": {
            "benchmark": tb_holdout["benchmark"],
            "independent_grader": True,
            "official_full_suite": False,
            "scope": tb_holdout["scope"],
            "agent_model": tb_holdout["agent_model"],
            "tasks": tb_holdout["task_count"],
            "repeats": tb_holdout["repeats_per_task"],
            "outcomes": _rate(holdout_passes, holdout_scored),
            "infrastructure_errors": _rate(
                tb_holdout["infra_errors"], holdout_scored
            ),
            "budget_exhaustion": _rate(
                tb_holdout["exit_reasons"].get("max_steps", 0)
                + tb_holdout["exit_reasons"].get("max_tokens", 0),
                holdout_scored,
            ),
            "total_cost_usd": tb_holdout["total_cost_usd"],
            "cost_per_scored_run_usd": tb_holdout["mean_cost_usd"],
            "cost_per_pass_usd": round(
                tb_holdout["total_cost_usd"] / holdout_passes, 4
            ),
            "stability": tb_holdout["stability"],
            "evidence_grade": "external-benchmark-disjoint-repeated-holdout",
        },
        "capability_development_baseline": {
            "benchmark": tb_baseline["benchmark"],
            "agent_model": "claude-haiku-4-5",
            "tasks": tb_baseline["n_tasks"],
            "repeats": tb_baseline["repeats"],
            "outcomes": _rate(passes, scored),
            "infrastructure_errors": _rate(infra_errors, scored),
            "budget_exhaustion": _rate(max_steps, scored),
            "total_cost_usd": tb_baseline["total_cost_usd"],
            "comparison_policy": (
                "Different model, task set, and budgets; retained as a diagnostic "
                "development baseline, not a causal comparison."
            ),
            "evidence_grade": "external-benchmark-development-subset",
        },
        "intervention_efficiency_external": {
            "benchmark": "Terminal-Bench 2.0 high-signal paired subset",
            "shared_tasks": tb_efficiency["n_shared_tasks"],
            "pass_rate_delta": tb_efficiency["pass_rate"],
            "step_delta": tb_efficiency["steps"],
            "cost_delta_usd": tb_efficiency["cost"],
            "decision": (
                "Step efficiency improved with CI excluding zero; no pass-rate or "
                "cost change was confirmed."
            ),
            "evidence_grade": "external-benchmark-paired",
        },
        "runtime_durability": {
            "experiment": recovery["experiment"],
            "controlled_process_exit_code": recovery["fault"]["process_exit_code"],
            "recovery_passed": recovery["final"]["passed"],
            "prefix_model_calls_reused": recovery["fault"]["prefix_model_calls"],
            "prefix_model_calls_reissued": recovery["recovery"][
                "reissued_prefix_model_calls"
            ],
            "prefix_tokens_reused": recovery["fault"]["prefix_tokens"],
            "prefix_cost_reused_usd": recovery["fault"]["prefix_cost_usd"],
            "checkpoint_write_p95_ms": recovery["checkpoint_metrics"]["latency_ms"]["p95"],
            "evidence_grade": "controlled-live-model-mechanism",
        },
        "evaluation_efficiency": {
            "experiment": prefix_benchmark["experiment"],
            "tasks": prefix["tasks"],
            "continuation_tokens": prefix["continuation_tokens"],
            "full_rerun_tokens": prefix["full_rerun_tokens"],
            "token_savings": prefix["token_savings"],
            "token_savings_fraction": prefix["token_savings_fraction"],
            "cost_savings_usd": prefix["cost_savings_usd"],
            "cost_savings_fraction": prefix["cost_savings_fraction"],
            "paired_token_delta": prefix[
                "paired_continuation_minus_full_tokens"
            ],
            "outcome_agreement": _rate(
                prefix["outcome_agreement_count"], prefix["tasks"]
            ),
            "evidence_grade": "paired-internal-mechanism",
        },
        "candidate_gate_case_study": {
            "comparison": candidate_screen["comparison"],
            "tasks": len(candidate_screen["task_ids"]),
            "observed_control_pass_rate": candidate_screen["control"]["outcomes"]["rate"],
            "observed_treatment_pass_rate": candidate_screen["treatment"]["outcomes"][
                "rate"
            ],
            "pass_rate_delta": screen["pass_rate_delta"],
            "mcnemar_exact": screen["mcnemar_exact"],
            "token_delta": screen["continuation_token_delta"],
            "cost_delta_usd": screen["continuation_cost_usd_delta"],
            "decision": "reject",
            "reason": candidate_screen["verdict"]["classification"],
            "evidence_grade": "paired-internal-gate-case-study",
        },
        "context_efficiency_mechanism": {
            "experiment": context_pilot["experiment"],
            "status": context_pilot["status"],
            "scope": context_pilot["scope"],
            "task_id": context_pilot["task_id"],
            "completed_model_calls": context_pilot["partial_usage"][
                "completed_model_calls"
            ],
            "first_compaction_estimated_tokens_before": context_pilot[
                "first_compaction"
            ]["estimated_tokens_before"],
            "first_compaction_estimated_tokens_after": context_pilot[
                "first_compaction"
            ]["estimated_tokens_after"],
            "first_compaction_reduction_percent": context_pilot[
                "first_compaction"
            ]["reduction_percent"],
            "dropped_complete_tool_turns": context_pilot["first_compaction"][
                "dropped_tool_turns"
            ],
            "supported_claims": context_pilot["supported_claims"],
            "unsupported_claims": context_pilot["unsupported_claims"],
            "evidence_grade": "development-partial-mechanism-unscored",
        },
        "holdout_v2_forecast": {
            "status": holdout_forecast["status"],
            "benchmark": holdout_forecast["benchmark"],
            "scope": holdout_forecast["scope"],
            "future_runs": holdout_forecast["future_runs"],
            "method": holdout_forecast["method"],
            "predictive": holdout_forecast["predictive"],
            "claims": holdout_forecast["claims"],
            "evidence_grade": "offline-forecast-unscored",
        },
        "claim_policy": [
            "The disjoint repeated Terminal-Bench holdout is the capability headline.",
            "The holdout is not an official full-suite leaderboard submission.",
            "Five-task native experiments support mechanism and gate-behavior claims only.",
            "Confidence intervals and denominators accompany every reported rate or delta.",
            "A directionally favorable but underpowered candidate is rejected, not promoted.",
            "Ungraded partial runs support mechanism claims only.",
            "Forecasts never appear as achieved benchmark results."
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    data = Path("docs/data")
    parser.add_argument("--tb-baseline", type=Path,
                        default=data / "tb_baseline_summary.json")
    parser.add_argument("--tb-holdout", type=Path,
                        default=data / "tb_holdout_v1_verifier_scorecard.json")
    parser.add_argument("--tb-efficiency", type=Path,
                        default=data / "tb_selfverify_comparison.json")
    parser.add_argument("--recovery", type=Path,
                        default=data / "durable_recovery_t01.json")
    parser.add_argument("--prefix-benchmark", type=Path,
                        default=data / "durable_counterfactual_multitask.json")
    parser.add_argument("--candidate-screen", type=Path,
                        default=data / "verification_candidate_comparison.json")
    parser.add_argument("--context-pilot", type=Path,
                        default=data / "budget_compaction_dev_pilot.json")
    parser.add_argument("--holdout-forecast", type=Path,
                        default=data / "tb_holdout_v2_forecast.json")
    parser.add_argument("--out", type=Path,
                        default=data / "benchmark_scorecard.json")
    args = parser.parse_args()
    scorecard = build_scorecard(
        _read(args.tb_baseline),
        _read(args.tb_holdout),
        _read(args.tb_efficiency),
        _read(args.recovery),
        _read(args.prefix_benchmark),
        _read(args.candidate_screen),
        _read(args.context_pilot),
        _read(args.holdout_forecast),
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(args.out, scorecard)
    print(json.dumps(scorecard, indent=2))


if __name__ == "__main__":
    main()
