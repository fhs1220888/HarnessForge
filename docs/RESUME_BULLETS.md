# Resume-ready project framing

Use two bullets, not all of them. The numbers below are backed by checked-in
evidence snapshots; keep the single-task qualifiers when discussing them.

## Recommended English bullets

- Built a durable, forkable coding-agent runtime with atomic turn checkpoints,
  versioned workspace snapshots, rollback, provenance guards, trace replay, and
  same-prefix counterfactual evaluation; covered by 96 deterministic tests.
- Ran a controlled live-model process-crash drill that resumed from checkpoint
  without replaying a 2-call, 2,845-token paid prefix, then completed successfully
  against an independent grader; observed 6.3 ms checkpoint-write p95 over eight
  local snapshots.
- Designed a same-prefix harness screening experiment that reduced incremental
  continuation usage by 9,438 tokens (24.5%) and cost by 23.6% versus independent
  full reruns in a one-task pilot, while explicitly measuring only 1/2 outcome
  agreement and documenting stochasticity/tooling confounds.

## Short project description

HarnessForge is a self-evolving coding-agent harness and evaluation lab. It treats
prompts, policies, tools, runtime state, and statistical evaluation as one system:
failures are traced, candidate harness revisions are isolated and measured, and
episodes can be resumed or forked from an exact committed model/workspace state.

## Interview guardrails

- The 24.5% token reduction is a one-task mechanism/cost pilot, not a population
  estimate or a claimed pass-rate lift.
- The 6.3 ms p95 covers eight tiny local workspace snapshots, not a production SLO.
- Native episodes are resumable; Terminal-Bench container snapshots and exactly-once
  external side effects remain explicit follow-up work.
- The strongest aggregate result remains the Terminal-Bench selfverify experiment:
  6.9% fewer steps, 95% CI [-13.3%, -1.6%], with no detected pass-rate change.

## Evidence map

- Crash/recovery drill: `docs/data/durable_recovery_t01.json`
- Same-prefix pilot: `docs/data/durable_counterfactual_t17.json`
- Aggregate experiments and caveats: `EXPERIMENTS.md`
