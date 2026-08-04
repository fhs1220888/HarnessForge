# Resume-ready project framing

Use two bullets, not all of them. The numbers below are backed by checked-in
evidence snapshots; keep the scope qualifiers when discussing them. For Chinese
applications, use the application/interview brief
[`PROJECT_BRIEF_ZH.md`](PROJECT_BRIEF_ZH.md#简历可直接使用); the longer benchmark
methodology remains in [`BENCHMARK_ZH.md`](BENCHMARK_ZH.md#简历可直接使用).

## Recommended English bullets

- Built a durable, forkable coding-agent runtime with atomic turn checkpoints,
  versioned workspace snapshots, rollback, provenance guards, trace replay, and
  same-prefix counterfactual evaluation; covered by the repository's deterministic
  test suite.
- Built an evidence-gated Self-Harness loop that mines failed trajectories, generates
  isolated declarative candidates, and promotes or rejects them through paired target
  and regression evaluation; completed 3 autonomous rounds / 6 live-model candidate
  gates with 2 automatic transitions, and confirmed 6.94% fewer steps on an external
  paired benchmark.
- Evaluated the harness on a frozen Terminal-Bench 2.0 holdout (8 unseen tasks ×
  2 independent runs): **11/16 = 68.75%** pass rate (Wilson 95% CI 44.4–85.8%),
  zero infrastructure errors, and a denominator-checked, reproducible scorecard.
- Ran a controlled live-model process-crash drill that resumed from checkpoint
  without replaying a 2-call, 2,845-token paid prefix, then completed successfully
  against an independent grader; observed 6.3 ms checkpoint-write p95 over eight
  local snapshots.
- Built a resumable multi-task counterfactual benchmark that atomically persists
  completed arms and separates source, reused-prefix, continuation, and full-control
  spend; across five live-model tasks, fork continuations used 30,307 fewer tokens
  (28.9%, paired CI for the mean delta excluded zero) while outcome agreement was
  only 3/5, demonstrating cheaper screening without claiming evaluation equivalence.

## Short project description

HarnessForge is a self-evolving coding-agent harness and evaluation lab. It treats
prompts, policies, tools, runtime state, and statistical evaluation as one system:
failures are traced, candidate harness revisions are isolated and measured, and
episodes can be resumed or forked from an exact committed model/workspace state.

## Interview guardrails

- The 28.9% reduction is a five-task, one-observation-per-task mechanism/cost
  benchmark, not a population estimate or a claimed pass-rate lift.
- The 6.3 ms p95 covers eight tiny local workspace snapshots, not a production SLO.
- Native episodes are resumable; Terminal-Bench container snapshots and exactly-once
  external side effects remain explicit follow-up work.
- The strongest aggregate result remains the Terminal-Bench selfverify experiment:
  6.9% fewer steps, 95% CI [-13.3%, -1.6%], with no detected pass-rate change.
- A development-only budget-compaction pilot reduced estimated first-compaction
  context from 12,271 to 3,795 tokens (69.1%). It was aborted by API credit before
  grading, so it supports a mechanism claim only, not pass-rate or cost causality.
- A new same-prefix verification candidate observed 4/5 versus 3/5 control but was
  correctly rejected: pass delta CI [-0.40, +0.80], McNemar p=1.0, tokens +6.64%,
  and cost +6.97%.

## Evidence map

- Crash/recovery drill: `docs/data/durable_recovery_t01.json`
- Same-prefix pilot: `docs/data/durable_counterfactual_t17.json`
- Multi-task same-prefix benchmark: `docs/data/durable_counterfactual_multitask.json`
- Four-axis scorecard: `docs/data/benchmark_scorecard.json`
- Self-Harness claim scorecard: `docs/data/selfharness_scorecard.json`
- Completed campaign scorecard: `docs/data/selfharness_campaign_v2_scorecard.json`
- Self-Harness causal proof protocol: `docs/SELF_HARNESS_EVIDENCE.md`
- Chinese recruiter/interview package: `docs/BENCHMARK_ZH.md`
- Chinese application and interview brief: `docs/PROJECT_BRIEF_ZH.md`
- Rejected candidate gate case: `docs/data/verification_candidate_comparison.json`
- Aggregate experiments and caveats: `EXPERIMENTS.md`
