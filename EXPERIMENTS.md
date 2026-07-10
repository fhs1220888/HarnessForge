# Experiment Log

Agent under test: `claude-haiku-4-5` · Miner/proposer: `claude-sonnet-5` ·
Budget: max 8 steps, $0.25/task · Suite: 18 tasks · Sandbox: local

## Baselines

| Run | Harness | Config | Pass rate | Cost | Notes |
|---|---|---|---|---|---|
| baseline (10 tasks) | 6f50180c | 30 steps | **1.000** (30/30) | $1.24 | Suite too easy — no headroom |
| baseline_v2 (18 tasks) | 6f50180c | 30 steps | **1.000** (54/54) | $2.32 | Harder tasks didn't help; modern models saturate small self-contained tasks |
| baseline_v4 (18 tasks) | f325df98 | **8 steps** | **0.667** (36/54) | $1.25 | Headroom via tight step budget. 40/54 runs hit max_steps |

**Design lesson:** headroom came from constraining the harness budget, not from
task difficulty or model choice (older weak models are retired from the API).
The experiment measures how much capability the harness preserves under constraint.

## Round 1 (self-harness iteration)

Mining on baseline_v4 failures found 3 patterns:
`patch-without-reverification` (freq 3), `diagnose-without-fix-csv-mismatch` (freq 2),
`blind-rewrite-after-traceback` (freq 1).

4 proposals passed pre-validation; gate (2 repeats) accepted 1:

> system_prompt.md: "The tool call immediately following any apply_patch must be
> the test command; do not read_file or re-inspect source before reverifying."
> Predicted delta +0.08 · validation targeted_delta +1.00 · regression_flips 0

Final full-suite: 0.667 → 0.583. Suspicious regression → ran a controlled A/B.

## A/B: the accepted rule, 9 borderline tasks × 3 repeats per arm

| Task | With rule | Without | Δ |
|---|---|---|---|
| t05_fix_regex | 3/3 | 1/3 | +0.67 |
| t09_fix_infinite_loop | 3/3 | 2/3 | +0.33 |
| t14_needle_in_haystack | 3/3 | 2/3 | +0.33 |
| t16_flatten_spec | 1/3 | 3/3 | −0.67 |
| t17_fix_csv_parser | 0/3 | 3/3 | −1.00 |
| t12 / t13 / t15 / t18 | = | = | 0 |
| **Total** | **21/27** | **22/27** | **≈0** |

t17 — the very task that justified the merge (2/2 in validation) — went 0/3 with
the rule and 3/3 without. Borderline tasks have true pass rates around 0.3–0.7;
at n=2–3 repeats, per-task results flip freely.

**Decisions:**
1. Reverted the rule (unproven changes must not accumulate).
2. Validation gate now requires effect size ≥ +0.25 (was: any positive delta).
3. Round driver default repeats 2 → 3.

**Calibration table, row 1:** predicted +0.08 · small-sample validation +1.00 ·
controlled A/B ≈ 0. Small-sample validation gates overfit; statistical power is
a first-class design constraint for self-improving harnesses.

## Reliability incidents (fixed in fixed-runtime code, not evolvable components)

1. No client timeout + SDK default retries → 27-minute silent hang on a retired
   model ID. Fix: explicit 120s timeout, SDK retries off, visible retry logging,
   404 = don't retry.
2. One task's API failure crashed the whole eval suite via `asyncio.gather`.
   Fix: per-task infra retry, then an explicit `api_error` outcome that is
   distinguishable from an agent failure.
3. Flaky network: exponential backoff with jitter (attempts 3 → 5).
