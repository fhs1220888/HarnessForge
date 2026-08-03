"""Offline posterior prediction for an explicitly unscored future holdout.

This module never turns a forecast into a benchmark result. It uses the observed
holdout-v1 denominator and a Jeffreys-prior Beta-Binomial model to describe what
an exchangeable 16-run follow-up could look like while API evaluation is unavailable.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from .tb_adapter import TB_HOLDOUT_V2


def _quantile(probabilities: list[float], probability: float) -> int:
    cumulative = 0.0
    for value, mass in enumerate(probabilities):
        cumulative += mass
        if cumulative >= probability:
            return value
    return len(probabilities) - 1


def beta_binomial_predictive(
    successes: int,
    trials: int,
    future_trials: int,
    prior_alpha: float = 0.5,
    prior_beta: float = 0.5,
) -> dict[str, Any]:
    """Return a posterior predictive summary for future Bernoulli runs."""
    if not 0 <= successes <= trials:
        raise ValueError("successes must be between zero and trials")
    if trials <= 0 or future_trials <= 0:
        raise ValueError("trials and future_trials must be positive")
    if prior_alpha <= 0 or prior_beta <= 0:
        raise ValueError("Beta prior parameters must be positive")

    alpha = prior_alpha + successes
    beta = prior_beta + trials - successes
    probabilities = []
    for future_successes in range(future_trials + 1):
        log_mass = (
            math.lgamma(future_trials + 1)
            - math.lgamma(future_successes + 1)
            - math.lgamma(future_trials - future_successes + 1)
            + math.lgamma(future_successes + alpha)
            + math.lgamma(future_trials - future_successes + beta)
            - math.lgamma(future_trials + alpha + beta)
            + math.lgamma(alpha + beta)
            - math.lgamma(alpha)
            - math.lgamma(beta)
        )
        probabilities.append(math.exp(log_mass))
    total_mass = sum(probabilities)
    probabilities = [mass / total_mass for mass in probabilities]

    expected_passes = sum(
        value * mass for value, mass in enumerate(probabilities)
    )
    return {
        "posterior_alpha": alpha,
        "posterior_beta": beta,
        "expected_passes": round(expected_passes, 4),
        "expected_pass_rate": round(expected_passes / future_trials, 4),
        "median_passes": _quantile(probabilities, 0.5),
        "central_95_passes": [
            _quantile(probabilities, 0.025),
            _quantile(probabilities, 0.975),
        ],
        "probability_at_least_8": round(sum(probabilities[8:]), 4),
        "probability_at_least_10": round(sum(probabilities[10:]), 4),
        "probability_at_least_11": round(sum(probabilities[11:]), 4),
    }


def build_forecast(
    observed: dict[str, Any], mechanism: dict[str, Any]
) -> dict[str, Any]:
    if mechanism.get("status") != "infra_aborted_unscored":
        raise ValueError("mechanism evidence must remain explicitly unscored")
    successes = int(observed["passed_runs"])
    trials = int(observed["scored_runs"])
    future_trials = len(TB_HOLDOUT_V2) * 2
    predictive = beta_binomial_predictive(successes, trials, future_trials)
    return {
        "schema_version": 1,
        "status": "forecast_unscored",
        "benchmark": "Terminal-Bench 2.0 holdout-v2 forecast",
        "scope": "8 metadata-frozen tasks x 2 hypothetical runs; no v2 API calls",
        "task_ids": TB_HOLDOUT_V2,
        "future_runs": future_trials,
        "source_observation": {
            "benchmark": observed["benchmark"],
            "passed_runs": successes,
            "scored_runs": trials,
            "pass_rate": observed["pass_rate"],
        },
        "method": {
            "model": "Beta-Binomial posterior predictive",
            "prior": "Jeffreys Beta(0.5, 0.5)",
            "assumption": "holdout-v2 runs are exchangeable with holdout-v1 runs",
            "difficulty_adjustment": "none",
        },
        "predictive": predictive,
        "controller_mechanism_observation": {
            "status": mechanism["status"],
            "first_compaction_reduction_percent": mechanism["first_compaction"][
                "reduction_percent"
            ],
            "tokens_through_partial_run": mechanism["partial_usage"]["tokens"],
            "used_to_shift_pass_forecast": False,
        },
        "non_probabilistic_scenarios": {
            "one_regression_vs_v1": {"passes": 10, "pass_rate": 0.625},
            "no_quality_effect": {"passes": 11, "pass_rate": 0.6875},
            "one_additional_recovery": {"passes": 12, "pass_rate": 0.75},
            "two_additional_recoveries": {"passes": 13, "pass_rate": 0.8125},
        },
        "claims": {
            "allowed": [
                "posterior predictive median is 11/16 under exchangeability",
                "mechanism telemetry supports context reduction",
            ],
            "forbidden": [
                "holdout-v2 achieved a measured pass rate",
                "the controller causally improves pass rate",
                "the forecast is an official Terminal-Bench score",
            ],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--observed", type=Path, required=True)
    parser.add_argument("--mechanism", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    forecast = build_forecast(
        json.loads(args.observed.read_text(encoding="utf-8")),
        json.loads(args.mechanism.read_text(encoding="utf-8")),
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(forecast, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
