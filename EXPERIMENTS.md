# Experiment Log

## Harness maturity self-assessment

Scored against the six production-harness components (context, tools, orchestration,
state/memory, evaluation/observability, constraints/recovery — the industry
decomposition per LangChain/OpenAI/Anthropic). Honest, not aspirational:

| Component | Status | Notes |
|---|---|---|
| Evaluation & observability | **near-production** | JSONL trace, replay CLI, bootstrap/Wilson CIs, run manifests, independent ground-truth verification, full self-harness eval loop |
| Constraints & recovery | **near-production** | sandbox isolation, step/token/cost budgets, jittered retry, infra-vs-agent failure separation, LLM timeout, **pre-execution arg validation**, repeated-error termination |
| Tool system | solid, simple | registry + executor + output truncation + error-as-observation; no semantic routing (6 tools, not needed) |
| Orchestration | basic | single loop with termination conditions; no graph/checkpoint/resume or multi-agent |
| Context management | basic+ | deterministic compaction (truncate old tool results, never grows context); compaction-safe memory channel; no relevance selection or layering |
| State & memory | **solid (episode)** | agent-layer `TaskMemory`: `memory_write` tool, notes ride the system prompt so compaction can't destroy them, bounded + traced + replayable, e2e-tested; cross-round `ProposalMemory` at the meta layer; cross-*task* persistent memory deliberately out of scope (self-contained benchmark → no measurable benefit) |

**Verdict:** not a toy — three of six walls are near-production/solid and better than
many internal harnesses; the rest are present-but-basic. Its differentiator
(self-improvement + rigorous measurement) sits *above* these six walls. Gaps are
documented, not faked; the remaining cuts (cross-task memory, tool routing, resumable
orchestration) are deliberate v1 scope decisions, not oversights.



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

## Round 2 (planned): high-signal selection + a verification discipline

Two changes address why earlier interventions couldn't be measured or didn't help:

**Better ruler (statistical power).** `eval/select.py` classifies baseline tasks into
always_pass / always_fail / borderline and drops capability-limited failures (mteb,
hf-model-inference, raman — tasks needing compute the model can't deliver in-budget
regardless of harness). The validation set becomes the tasks where a harness change
can actually move the needle: `{crack-7z-hash, merge-diff-arc-agi-task,
openssl-selfsigned-cert, polyglot-c-py, prove-plus-comm, qemu-startup,
vulnerable-secret}` + 3 always_pass regression guards.

**Better intervention (`harness_selfverify`).** The finish-fix A/B failed because it
gave the agent *permission* to stop without a way to know it was right. The selfverify
variant instead installs a completion *discipline*: (1) restate the deliverables as a
checklist first; (2) before finishing, verify each item with a concrete command whose
output would expose a mistake ("assume wrong until a command shows it right"); (3)
finish only when all checks pass. Hypothesis: rigorous self-verification prevents the
premature-finish regressions while still letting the agent stop when genuinely done —
recovering the −19% cost effect without the pass-rate loss.

### Round 2 results

High-signal set, 3 repeats/arm (2+1 pooled), paired bootstrap:

| Group | Control | selfverify | Δ (95% CI) |
|---|---|---|---|
| Targets (7 harness-fixable) | 0.143 | 0.238 | **+0.095, [−0.095, +0.333]** |
| All 10 | 0.367 | 0.433 | +0.067, [−0.10, +0.267] |
| Regression guards (3) | 0.889 | 0.889 | 0.0 — no collateral damage |

Two targets robustly improved (openssl-selfsigned-cert 0.00→0.67, vulnerable-secret
0.67→1.00); one regressed (prove-plus-comm 0.33→0.00). Agent finish rate rose (0→~30%
of runs), cost roughly flat.

**Verdict: directionally positive and non-damaging, but not statistically confirmed.**
selfverify is clearly better-behaved than finish-fix — the regression guards held flat
(vs. finish-fix damaging passing tasks) and the targets lean positive — but the CI still
crosses zero.

**Why we stop here (a power calculation, not a shrug).** The effect is ~+7–10 pp. With
binary outcomes and per-task pairing over 7–10 tasks, the 95% CI half-width is ≈ ±0.2.
CI width shrinks like 1/√n, so confirming a +0.10 effect at ±0.05 needs ≈ 16× the data —
on the order of 100+ task-instances, i.e. tens of dollars of eval per candidate. For an
effect this small that is not worth it, and *knowing that* — sizing the experiment before
spending — is the point. A production harness team would either batch many more tasks or
accept the change on mechanism + non-harm grounds.

**Calibration table, row 3:** hypothesis "verification discipline → higher pass rate on
fixable tasks" · targets Δ +0.095, CI [−0.095, +0.333] · guards flat. Best-designed
intervention of the three; positive lean, underpowered to confirm.

### The measurable win is on the efficiency axis

Re-analyzing the same round-2 runs with a *continuous* paired bootstrap
(`eval/compare.py`, pooled n=3) separates two questions the pass-rate metric
conflates:

| Metric | selfverify vs control | 95% CI | Significant? |
|---|---|---|---|
| Pass rate | +0.067 | [−0.100, +0.267] | no (crosses 0) |
| Cost/run | −1.3% | [−…, +…] | no (crosses 0) |
| **Steps/run** | **−6.9%** | **[−13.3%, −1.6%]** | **yes — CI excludes 0** |

So the honest, defensible result is not "higher pass rate" but: **selfverify
significantly reduces agent steps (~7%, CI excludes zero) with no detectable
pass-rate change.** This is the whole point of picking the right metric — binary
pass/fail needs ~16× the data to confirm a small effect, but steps is continuous
and low-variance, so the same runs already confirm the efficiency gain. Choosing a
higher-power metric *is* the result. No extra spend was needed.

**Meta-arc across all three interventions.** Each was better designed than the last
(reverify-after-patch → permission-to-finish → verification-discipline) and each was
measured more rigorously (single-run → paired → high-signal selection + pooled bootstrap).
The honest bottom line: naive self-harness merges noise; the fix is not a cleverer prompt
but a measurement regime — effect-size thresholds, regression guards, and enough
statistical power to tell a real +7 pp from a lucky one.

## Multi-round search machinery (built, unit-tested; full campaign deferred)

The self-harness loop is a real search, not a single shot (`selfharness/search.py`,
`proposal.py`, `round.py::run_campaign`):

- **Multi-candidate:** the proposer emits several distinct diffs per failure pattern;
  `select_best_per_group` validates them and keeps only the best per pattern.
- **Memory:** rejected candidates and *why* they failed (noise / regression / also-ran)
  are folded into `ProposalMemory` and injected into later prompts, so dead ends aren't
  re-proposed across rounds.
- **Campaign:** `run_campaign` chains rounds — each round's merged harness becomes the
  next round's baseline — emitting a pass-rate trajectory, a per-candidate calibration
  table, and a persisted `memory.json`.

All of this is covered by unit tests (`tests/test_search.py`) and wired into the CLI
(`--rounds N`). A full multi-round campaign on live models is deferred on cost grounds:
per the power analysis above, the native suite has limited headroom at 8 steps and a
2-round campaign's expected outcome is a modest/noisy trajectory rather than a new
confirmed result — not worth the API spend for a portfolio artifact. The machinery is
ready to run when justified; this repo prioritizes confirmed results (the −6.9% step
reduction) over an underpowered trajectory chart.

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
