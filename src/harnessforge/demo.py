"""Offline recruiter-facing evidence demo.

This command makes no model, network, or Docker calls. It rebuilds the benchmark
scorecard from checked-in evidence, refuses drift, and renders the four claims plus
the rejected-candidate case study in a compact terminal narrative.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .eval.benchmark_scorecard import build_scorecard

DEFAULT_DATA = Path(__file__).parents[2] / "docs" / "data"


def _read(data_dir: Path, name: str) -> dict[str, Any]:
    return json.loads((data_dir / name).read_text(encoding="utf-8"))


def verified_scorecard(data_dir: Path = DEFAULT_DATA) -> dict[str, Any]:
    """Rebuild the scorecard and reject stale or hand-edited headline metrics."""
    data_dir = Path(data_dir)
    generated = build_scorecard(
        _read(data_dir, "tb_baseline_summary.json"),
        _read(data_dir, "tb_holdout_v1_verifier_scorecard.json"),
        _read(data_dir, "tb_selfverify_comparison.json"),
        _read(data_dir, "durable_recovery_t01.json"),
        _read(data_dir, "durable_counterfactual_multitask.json"),
        _read(data_dir, "verification_candidate_comparison.json"),
    )
    checked = _read(data_dir, "benchmark_scorecard.json")
    if generated != checked:
        raise RuntimeError(
            "benchmark_scorecard.json drifted from its evidence inputs; regenerate it"
        )
    return checked


def _pct(value: float) -> str:
    return f"{100 * value:.1f}%"


def render_demo(scorecard: dict[str, Any]) -> str:
    capability = scorecard["capability_external"]
    outcomes = capability["outcomes"]
    efficiency = scorecard["intervention_efficiency_external"]
    recovery = scorecard["runtime_durability"]
    evaluation = scorecard["evaluation_efficiency"]
    gate = scorecard["candidate_gate_case_study"]

    pass_ci = outcomes["wilson_ci95"]
    step = efficiency["step_delta"]
    token_ci = evaluation["paired_token_delta"]
    gate_pass = gate["pass_rate_delta"]
    gate_tokens = gate["token_delta"]
    gate_cost = gate["cost_delta_usd"]
    lines = [
        "HarnessForge — offline evidence demo",
        "====================================",
        "No API key, network, or Docker required. Scorecard integrity: VERIFIED",
        "",
        "[1/4] External capability — Terminal-Bench 2.0 holdout-v1",
        f"  PASS  {outcomes['successes']}/{outcomes['observations']} = "
        f"{_pct(outcomes['rate'])}  Wilson 95% CI "
        f"[{_pct(pass_ci[0])}, {_pct(pass_ci[1])}]",
        f"  INFRA {capability['infrastructure_errors']['successes']}/"
        f"{outcomes['observations']} errors  COST "
        f"${capability['cost_per_scored_run_usd']:.4f}/scored run",
        "  SCOPE 8 pinned holdout tasks x 2; not an official full-suite score",
        "",
        "[2/4] External paired intervention — efficiency",
        f"  STEPS {step['pct_change']:+.2f}%  mean delta {step['mean_delta']:+.4f} "
        f"95% CI [{step['ci_low']:+.4f}, {step['ci_high']:+.4f}]",
        "  RESULT confirmed step reduction; pass-rate and cost changes unconfirmed",
        "",
        "[3/4] Controlled crash -> resume",
        f"  EXIT {recovery['controlled_process_exit_code']} after checkpoint; reused "
        f"{recovery['prefix_model_calls_reused']} calls / "
        f"{recovery['prefix_tokens_reused']:,} tokens",
        f"  REPLAY {recovery['prefix_model_calls_reissued']} prefix calls  "
        f"GRADER {'PASS' if recovery['recovery_passed'] else 'FAIL'}  "
        f"checkpoint p95 {recovery['checkpoint_write_p95_ms']:.3f} ms",
        "",
        "[4/4] Exact-prefix evaluation efficiency",
        f"  TOKENS {evaluation['token_savings']:,} saved "
        f"({_pct(evaluation['token_savings_fraction'])}); paired delta CI "
        f"[{token_ci['ci_low']:,.0f}, {token_ci['ci_high']:,.0f}] tokens/task",
        f"  AGREEMENT {evaluation['outcome_agreement']['successes']}/"
        f"{evaluation['outcome_agreement']['observations']} — screening, not a "
        "full-eval replacement",
        "",
        "Promotion gate case study",
        f"  OBSERVED pass rate {gate['observed_control_pass_rate']:.1%} -> "
        f"{gate['observed_treatment_pass_rate']:.1%}, but paired CI "
        f"[{gate_pass['ci_low']:+.2f}, {gate_pass['ci_high']:+.2f}]",
        f"  REGRESSION tokens {gate_tokens['pct_change']:+.2f}%  "
        f"cost {gate_cost['pct_change']:+.2f}%  "
        f"McNemar p={gate['mcnemar_exact']['two_sided_p_value']:.1f}",
        f"  DECISION {gate['decision'].upper()} — {gate['reason']}",
        "",
        "Evidence: BENCHMARK.md and docs/data/benchmark_scorecard.json",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--json", action="store_true", help="print verified JSON")
    args = parser.parse_args()
    scorecard = verified_scorecard(args.data_dir)
    print(json.dumps(scorecard, indent=2) if args.json else render_demo(scorecard))


if __name__ == "__main__":
    main()
