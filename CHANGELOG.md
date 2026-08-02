# Changelog

## 0.1.0 — 2026-08-03

First portfolio-ready release candidate.

### Runtime

- Atomic turn-boundary checkpoints for messages, memory, guards, token/cost ledger,
  and versioned workspace snapshots.
- Crash resume with prompt/harness provenance checks and completed-result recovery.
- Historical checkpoint forks with isolated candidate workspaces.
- Process-group timeout cleanup, truthful patch failures, permanent-4xx fail-fast,
  and explicit infrastructure outcomes.

### Evaluation

- Resumable multi-task same-prefix counterfactual benchmark with optional full-rerun
  controls and soft experiment cost caps.
- Paired candidate comparator with prefix-consistency guards, bootstrap intervals,
  outcome flips, and exact McNemar analysis.
- Four-axis benchmark scorecard: external capability, external intervention
  efficiency, runtime durability, and evaluation efficiency.
- Golden evidence test and offline `make demo`; neither requires an API key,
  network, Docker, nor untracked run directories.

### Evidence

- Terminal-Bench 2.0 subset: 19/40 pass, Wilson 95% CI [32.9%, 62.5%], 0/40
  infrastructure errors.
- External paired intervention: 6.94% fewer steps with interval excluding zero;
  pass-rate and cost changes unconfirmed.
- Controlled crash/resume: two paid calls and 2,845 tokens reused with zero prefix
  calls reissued; final independent grader passed.
- Five-task prefix benchmark: 28.9% fewer continuation tokens/cost than full reruns,
  with only 3/5 outcome agreement explicitly reported.
- Verification candidate rejected despite an observed 4/5 versus 3/5 control because
  quality was underpowered and continuation tokens/cost increased.

### Known boundaries

- Terminal-Bench container filesystems are not checkpointed.
- Filesystem recovery does not imply exactly-once external side effects.
- Five-task native studies are mechanism/gate case studies, not capability claims.
- Local checkpoint latency covers eight tiny snapshots and is not a production SLO.
