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

## 1. External capability benchmark

Terminal-Bench 2.0 subset, 20 pinned tasks × 2 repeats, independent task graders,
`claude-haiku-4-5`, 25-step budget.

| Metric | Result |
|---|---:|
| Pass rate | **19/40 = 47.5%** |
| Wilson 95% interval | **[32.9%, 62.5%]** |
| Infrastructure errors | **0/40** |
| Max-step exits | 36/40 = 90.0% |
| Total model cost | $10.38 |
| Cost per scored run | $0.2595 |
| Cost per grader pass | $0.5463 |

This is the capability headline because the benchmark and graders are external.
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

## Evidence and claim policy

- [Machine-readable scorecard](docs/data/benchmark_scorecard.json)
- [Terminal-Bench baseline](docs/data/tb_baseline_summary.json)
- [External paired intervention](docs/data/tb_selfverify_comparison.json)
- [Crash/recovery drill](docs/data/durable_recovery_t01.json)
- [Multi-task prefix benchmark](docs/data/durable_counterfactual_multitask.json)
- [Rejected candidate comparison](docs/data/verification_candidate_comparison.json)

Claim rules:

1. External Terminal-Bench results are the capability headline.
2. Five-task native experiments support mechanism and gate-behavior claims only.
3. Every rate or delta carries its denominator and interval.
4. Non-confirmation is not described as equivalence.
5. A favorable point estimate is rejected when the predeclared gate is not met.
