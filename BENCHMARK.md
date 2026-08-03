# Benchmark scorecard

HarnessForge reports four separate axes instead of a composite score. Capability,
efficiency, runtime durability, and evaluation efficiency have different
denominators and failure consequences; collapsing them into one number would hide
the trade-offs a harness engineer is expected to manage.

The checked-in machine-readable scorecard is generated from evidence snapshots and
guarded by a golden test:

```bash
python -m harnessforge.eval.benchmark_scorecard
pytest -q tests/test_benchmark_scorecard.py
```

For Chinese recruiting, the same evidence is packaged as a 30-second project pitch,
resume bullets, and interview Q&A in [docs/BENCHMARK_ZH.md](docs/BENCHMARK_ZH.md).

![HarnessForge measured evidence](docs/figures/industrial/15-readme-hero.png)

## Evidence ladder

| Tier | Headline | Claim boundary |
|---|---|---|
| Measured external capability | **11/16 = 68.75%** on frozen holdout-v1 | Primary capability result; not an official full-suite score |
| Measured external efficiency | **6.94% fewer steps**, CI excludes zero | Paired intervention result; pass-rate lift remains unconfirmed |
| Measured system mechanisms | **28.9%** same-prefix token/cost savings; **0** prefix calls replayed after crash | Cost and durability mechanisms; not population-level quality estimates |
| Unscored development telemetry | First compaction **12,271 → 3,795 estimated tokens (−69.1%)** | Controller activation only; no pass-rate or causal cost claim |
| Offline forecast | v2 median **11/16**, predictive interval **5–15** | Planning artifact only; no v2 run was scored |

## 1. External capability benchmark

Terminal-Bench 2.0 `holdout-v1`, 8 metadata-pinned tasks × 2 independent runs,
independent task graders, `claude-sonnet-5`, mandatory verifier Harness, 40-step
budget. The holdout was fixed before task instructions/tests were inspected and is
disjoint from the 20-task development subset.

| Metric | Result |
|---|---:|
| Pass rate | **11/16 = 68.75%** |
| Wilson 95% interval | **[44.4%, 85.8%]** |
| Infrastructure errors | **0/16** |
| Budget exits | 8/16 = 50.0% |
| Total model cost | $18.96 |
| Cost per scored run | $1.1851 |
| Cost per grader pass | $1.7239 |
| Task stability | 4 pass 2/2; 3 pass 1/2; 1 fails 0/2 |

This is the capability headline because the benchmark and graders are external and
the tasks were held out from development. It is an 8-task subset result, **not** an
official 89-task leaderboard submission. The older Haiku development result remains
19/40 = 47.5%, but uses a different model/task set/budget and is not a causal baseline.
The native suite is useful for fast regression and controlled mechanisms, but it is
not presented as a substitute for Terminal-Bench.

## 2. External paired intervention benchmark

The verification-discipline intervention was evaluated on a 10-task high-signal
Terminal-Bench subset with three pooled observations per arm.

| Paired treatment − control metric | Mean | 95% interval | Decision |
|---|---:|---:|---|
| Pass rate | +0.067 | [−0.100, +0.267] | not confirmed |
| Cost/run | −1.34% | [−$0.0298, +$0.0231] | not confirmed |
| Steps/run | **−6.94%** | **[−3.33, −0.40]** | confirmed efficiency gain |

The pass-rate claim is deliberately weaker than the step-efficiency claim because
the binary metric is underpowered at this sample size.

## 3. Runtime durability benchmark

A controlled process exit occurred immediately after checkpoint 2 during a live
model run. Resume restored the committed model/workspace state and budget ledger.

| Metric | Result |
|---|---:|
| Paid prefix reused | 2 model calls / 2,845 tokens / $0.003621 |
| Prefix calls reissued | **0** |
| Final grader | **2/2 pass** |
| Checkpoint write p95 | 6.304 ms over 8 tiny local snapshots |

This is a mechanism test, not a production availability SLO. Container snapshotting
and exactly-once external effects remain explicit boundaries.

## 4. Evaluation-efficiency benchmark

Five native tasks paired a continuation from a predeclared midpoint checkpoint with
an independent full rerun.

| Metric | Fork continuation | Full rerun | Difference |
|---|---:|---:|---:|
| Tokens | 74,662 | 104,969 | **−30,307 (−28.9%)** |
| Cost | $0.091406 | $0.128533 | **−$0.037127 (−28.9%)** |
| Grader outcomes | 3/5 pass | 5/5 pass | agreement only 3/5 |

The paired token delta interval is [−8,263, −3,921] tokens/task. Low outcome
agreement is reported beside the savings: same-prefix forks are a cheaper candidate
screen and diagnostic tool, not a replacement for powered full evaluation.

## Candidate-gate case study: reject the attractive number

A single-variable candidate added only a verification-discipline prompt while
keeping tools, memory, policy, budgets, and the finish-test gate identical. From the
same five prefixes it observed 4/5 passes versus control's 3/5, but the gate rejected
it:

- paired pass-rate delta +0.20, interval [−0.40, +0.80];
- exact McNemar p = 1.0 (two treatment-only flips, one control-only flip);
- continuation tokens **+6.64%**, interval entirely above zero;
- continuation cost **+6.97%**, interval entirely above zero;
- no step reduction; every arm exhausted all eight steps.

This is the intended self-improvement behavior: a directionally favorable small
sample does not earn promotion when quality is unconfirmed and efficiency regresses.

## Budget-pressure context controller

One Terminal-Bench development task activated the budget-aware compaction controller
after cumulative token use crossed its configured threshold. The first compaction
replaced 11 complete old tool turns with a bounded ledger and reduced estimated
context from 12,271 to 3,795 tokens (**69.1%**). Across the partial trajectory, 20
post-trigger calls averaged 6,756.7 input tokens versus a pre-trigger final call of
18,768.

The run ended with `credit_balance_too_low` after 37 completed calls and before a
reward was available. It is therefore stored as `infra_aborted_unscored`: it verifies
that the mechanism activates and bounds late context, but does not support a pass-rate,
completion-rate, or causal cost-reduction claim.

## Frozen holdout-v2: forecast, not result

No holdout-v2 API call was made. An offline Jeffreys-prior Beta-Binomial forecast,
based only on holdout-v1, has a posterior-predictive median of 11/16 and a central
95% interval of 5–15 passes. The forecast is useful for budgeting the next measured
run; it is not a benchmark score and is excluded from every resume headline.

## Evidence and claim policy

- [Machine-readable scorecard](docs/data/benchmark_scorecard.json)
- [Terminal-Bench holdout scorecard](docs/data/tb_holdout_v1_verifier_scorecard.json)
- [Terminal-Bench baseline](docs/data/tb_baseline_summary.json)
- [External paired intervention](docs/data/tb_selfverify_comparison.json)
- [Crash/recovery drill](docs/data/durable_recovery_t01.json)
- [Multi-task prefix benchmark](docs/data/durable_counterfactual_multitask.json)
- [Rejected candidate comparison](docs/data/verification_candidate_comparison.json)
- [Budget-compaction development pilot](docs/data/budget_compaction_dev_pilot.json)
- [Unscored holdout-v2 forecast](docs/data/tb_holdout_v2_forecast.json)

Claim rules:

1. The disjoint repeated Terminal-Bench holdout is the capability headline.
2. The holdout is not described as an official full-suite score.
3. Five-task native experiments support mechanism and gate-behavior claims only.
4. Every rate or delta carries its denominator and interval.
5. Non-confirmation is not described as equivalence.
6. A favorable point estimate is rejected when the predeclared gate is not met.
7. Forecasts and ungraded partial runs never appear as achieved benchmark results.
