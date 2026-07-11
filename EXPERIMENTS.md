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

## Terminal-Bench baseline (external benchmark)

`tb-subset-v1`: 20 pinned Terminal-Bench 2.0 tasks (easy/medium, expert time
5–30 min), run in each task's prebuilt Docker image, verified by TB's own
reward.txt. Same harness components as the native suite; only the budget is
larger (25 steps) because TB tasks are far harder.

| Run | Harness | Config | Pass rate | Cost | Notes |
|---|---|---|---|---|---|
| tb_baseline | f325df98 | 25 steps, 2 repeats | **0.475** (19/40) | $10.38 | 0 infra_error. Real external-benchmark number |

**Dominant finding — the agent almost never stops.** 36/40 runs exhausted the
25-step budget; only 3 called `finish`. Even *passing* tasks (cobol, extract-elf,
pytorch-model-recovery, git-leak-recovery, …) hit max_steps: the agent completed
the work but never recognized it was done, and kept probing with bash.

Root cause is a harness/task-distribution mismatch. On the native suite the agent
confirms success by running pytest (visible) and then finishes. On TB, verification
is external and hidden (TB writes reward.txt via a test.sh the agent never sees),
so the agent is never confident it is done. The `run_tests_before_finish` gate and
the `_looks_like_test` heuristic — both tuned for the native pytest suite — misfire
on TB. Tool usage confirms the flailing: 15–25 bash calls per run, read_file barely
used (0–6).

Two harness-level opportunities this exposes:
1. **Pass rate:** give the agent a way to self-verify / decide it is done on
   TB-style tasks, so it stops flailing before the budget runs out.
2. **Cost/efficiency:** 36/40 runs burn the full 25-step budget, which is most of
   the $10.38. A harness that lets the agent finish when done should cut cost
   substantially at equal pass rate ("self-harness for efficiency").

Per-run breakdown (final 40 scored runs): 9 tasks pass 2/2, 10 fail 0/2,
1 flaky (vulnerable-secret 1/2).

## TB finish-behavior A/B (hand-crafted intervention)

Hypothesis from the baseline finding: the agent burns the full 25-step budget
because it never recognizes completion. Treatment harness (`harness_finish_fix`):
(1) system_prompt gains a "Recognizing completion" section — do one verification
pass, then `finish` immediately instead of flailing; (2) loop_policy sets
`run_tests_before_finish: false`, since TB has no agent-visible test to gate on.

Control = the tb_baseline slice for the same 10 tasks (repeats 2). Treatment =
`--harness-dir harness_finish_fix`, same 10 tasks, repeats 2.

| Metric | Control | Treatment | Δ |
|---|---|---|---|
| Pass rate | 0.500 | 0.400 | −0.10 (95% CI **[−0.30, +0.10]**, crosses 0) |
| `finish` / `max_steps` | 0 / 20 | 8 / 12 | agent now stops on its own |
| Avg steps/run | 25.0 | 23.1 | −1.9 |
| Avg cost/run | $0.196 | $0.158 | **−19%** |

Per-task: 3 previously-passing tasks (cobol, extract-elf, code-from-image) fell
2/2 → 1/2; one failing task (prove-plus-comm) gained. The intervention did exactly
what it said — the agent finishes earlier and cheaper — but that early finishing is
often *premature*: on TB the verification is hidden, so the agent's self-judgment of
"done" is unreliable, and it declares victory before the work is actually complete.

**Lesson:** the `run_tests_before_finish` gate I removed was load-bearing — it was
suppressing premature completion. Budget-burning was not pure waste; it correlated
with eventually getting there. You cannot cheaply buy efficiency by telling the
agent to stop; you need a *reliable completion signal*, which hidden verification
denies. A real fix must add genuine self-verification, not just permission to quit.

**Calibration table, row 2:** hypothesis "help the agent finish → higher pass rate"
· measured pass-rate Δ −0.10 (CI crosses 0) · clear −19% cost effect. Same meta-
lesson as round 1: locally plausible harness changes must be measured, not assumed.

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
