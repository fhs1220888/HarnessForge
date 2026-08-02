# Resume-ready project framing

Use two bullets, not all of them. The numbers below are backed by checked-in
evidence snapshots; keep the scope qualifiers when discussing them.

## Recommended English bullets

- Built a durable, forkable coding-agent runtime with atomic turn checkpoints,
  versioned workspace snapshots, rollback, provenance guards, trace replay, and
  same-prefix counterfactual evaluation; covered by 104 deterministic tests.
- Evaluated the harness on 40 independently graded Terminal-Bench 2.0 runs:
  47.5% pass rate (Wilson 95% CI 32.9–62.5%), zero infrastructure errors, and
  $0.2595 per scored run; published a denominator-checked four-axis scorecard.
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
- A new same-prefix verification candidate observed 4/5 versus 3/5 control but was
  correctly rejected: pass delta CI [-0.40, +0.80], McNemar p=1.0, tokens +6.64%,
  and cost +6.97%.

## Evidence map

- Crash/recovery drill: `docs/data/durable_recovery_t01.json`
- Same-prefix pilot: `docs/data/durable_counterfactual_t17.json`
- Multi-task same-prefix benchmark: `docs/data/durable_counterfactual_multitask.json`
- Four-axis scorecard: `docs/data/benchmark_scorecard.json`
- Rejected candidate gate case: `docs/data/verification_candidate_comparison.json`
- Aggregate experiments and caveats: `EXPERIMENTS.md`
