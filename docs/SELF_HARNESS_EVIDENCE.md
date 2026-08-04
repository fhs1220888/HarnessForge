# Self-Harness evidence and causal proof protocol

HarnessForge is an **evidence-gated self-improving coding-agent harness**. Its
distinguishing loop is not prompt editing by hand:

```text
agent trajectories
    -> failure-pattern mining
    -> several declarative harness candidates per pattern
    -> isolated sibling revisions
    -> paired target + regression evaluation
    -> promote one winner or reject every candidate
    -> persist rejected-attempt memory for the next round
```

The machine-readable evidence card is generated from checked-in live-model runs:

```bash
python -m harnessforge.selfharness.evidence
pytest -q tests/test_selfharness_evidence.py tests/test_selfharness_proof.py \
  tests/test_campaign_audit.py
```

## What has been demonstrated

| Self-Harness property | Evidence | Status |
|---|---|---|
| Closed-loop search | 3 completed rounds; 6 live-model gates; 2 automatic transitions | confirmed |
| Selective promotion | 1 promotion, 5 rejections | demonstrated |
| Cross-round memory | rejected and also-ran proposals persisted for later prompts | demonstrated in code and tests |
| Measured self-improvement | Terminal-Bench paired steps/run **−6.94%**, 95% interval excludes zero | confirmed for efficiency |
| Noise resistance | an apparent 4/5 vs 3/5 candidate was rejected when CI crossed zero and token/cost regressed | demonstrated |
| Overall pass-rate uplift | paired delta +6.67 pp, CI [−10.0, +26.67] pp | not confirmed |
| Multi-round unattended execution | 3 rounds, 3 final full-suite evaluations, 0 manual interventions | confirmed |
| 68.75% as causal uplift | holdout and development baseline used different model/task/budget protocols | not a causal comparison |

This distinction is deliberate. A self-improving system is unsafe if it treats every
favorable point estimate as an improvement. HarnessForge records a candidate as an
improvement only when the predeclared metric and regression gate pass.

## Existing multi-round evidence

The checked-in campaign audit contains three completed rounds and six candidate gates:

- Round 1: two candidates, one promoted and one rejected; Pass Rate 55.6% -> 75.0%.
- Round 2: three candidates, all rejected; the unchanged Harness scored 63.9%, exposing
  substantial repeat-to-repeat variance rather than a real Harness regression.
- Round 3: one candidate, rejected after zero targeted gain and one regression flip;
  the unchanged final Harness scored 72.2%.
- Across the full campaign: 244 agent task-runs, 1 promotion / 5 rejections, zero
  API/infra/timeout outcomes, and $6.1404 recorded agent-execution cost. Meta-layer
  mining/proposal cost was not captured by the historical meter and is not included.
- Earlier calibration exposed a false positive: a candidate predicted at +8 pp and
  observed at +100 pp on a tiny validation set reproduced at approximately zero in a
  9-task × 3-repeat controlled A/B, so it was reverted.

The current resume-safe claim is therefore:

> Completed a three-round unattended Self-Harness campaign with six live-model gates
> and two automatic round transitions; promoted one candidate, rejected five, and
> confirmed a separate 6.94% step-efficiency improvement on an external paired benchmark.

The development-suite round-0/final delta was +16.67 pp with paired 95% interval
[0, +36.11] pp. It is not a causal holdout result because the same tasks informed the
search and the interval lower bound is not above zero.

## Crash-safe autonomous campaign

`selfharness.round --rounds N` now executes against isolated campaign-local Harness
revisions instead of mutating the repository Harness during search. Proposal diffs are
generated against that round's current isolated revision, not the repository parent.
It atomically writes `campaign_report.json` after every completed round.

The report records:

- frozen protocol and initial baseline;
- running, interrupted, budget-exhausted, or completed status;
- completed rounds and current round;
- automatic transitions between rounds;
- pass-rate trajectory;
- per-round reports and resume count;
- number of fully committed rounds recovered after a hard process loss;
- confirmation that the repository Harness was not mutated.
- exact agent/meta/total calls, tokens, and USD spend for newly run campaigns;
- configured campaign ceiling, observed spend, and remaining budget.

If the process exits during a round, the report remains valid. `--resume` refuses
protocol drift. A fully committed but not yet campaign-indexed round is recovered
after checking its Harness version, avoiding duplicate model spend; a partial round is
archived before the last completed parent revision is restored. Archived partial-run
usage remains in the campaign total because it was real billed work. The budget guard
runs between evaluation stages: a stage already in flight can finish and slightly
overshoot, but no later stage starts after the ceiling is observed. The ceiling is an
operational control rather than part of the evaluation protocol, so a
`budget_exhausted` campaign can resume with a higher ceiling.

Example:

```bash
python -m harnessforge.selfharness.round \
  --tasks tasks \
  --out runs/selfharness-causal-campaign \
  --baseline runs/frozen-round0-baseline \
  --regression-tasks t01_fix_off_by_one t05_fix_regex t09_fix_infinite_loop \
  --rounds 3 --repeats 3 --candidates-per-pattern 3 --sandbox local \
  --max-campaign-cost-usd 20

# Same protocol after an infrastructure interruption:
python -m harnessforge.selfharness.round \
  --tasks tasks \
  --out runs/selfharness-causal-campaign \
  --baseline runs/frozen-round0-baseline \
  --regression-tasks t01_fix_off_by_one t05_fix_regex t09_fix_infinite_loop \
  --rounds 3 --repeats 3 --candidates-per-pattern 3 --sandbox local --resume \
  --max-campaign-cost-usd 25
```

The checked-in 2026-08 campaign predates meta-layer metering, so its published
`$6.1404` is explicitly agent-task spend only. Do not retroactively label it a total.
New campaigns write `meta_usage.json` per round and expose the combined amount under
`campaign_report.json -> budget.observed.total`.

Completing three rounds proves that the search/gate loop operated autonomously across
at least two round transitions. It does **not by itself** prove that pass rate improved.

## Predeclared causal pass-rate test

To promote “Self-Harness improves overall Pass Rate” from a hypothesis to a result,
the final promoted revision must be compared with the immutable round-0 parent under
one protocol:

1. Freeze at least 20 disjoint holdout tasks before opening their instructions/tests.
2. Run both parent and final Harness on the same model, task set, images, budgets,
   temperature and number of repeats.
3. Use at least two repeats per task and alternate/control execution order where
   practical to reduce temporal provider effects.
4. Compute the paired task-level Pass Rate delta and its 95% interval.
5. Claim causal uplift only if the interval's lower bound is above zero and no
   regression gate is breached.
6. If the first-stage interval crosses zero, report “not confirmed”; do not select the
   better repeat or combine a different model/task baseline.

The final report is produced by a strict wrapper, not by manually comparing two
percentages. It rejects model/task/content hash/container/revision/budget/repeat drift
before computing the paired interval:

```bash
python -m harnessforge.selfharness.proof \
  --control runs/selfharness-final-ab/control-repeat1 \
            runs/selfharness-final-ab/control-repeat2 \
  --treatment runs/selfharness-final-ab/treatment-repeat1 \
              runs/selfharness-final-ab/treatment-repeat2 \
  --minimum-tasks 20 --minimum-repeats 2 \
  --out runs/selfharness-final-ab/causal_proof.json

python -m harnessforge.selfharness.evidence \
  --campaign-report runs/selfharness-causal-campaign/campaign_report.json \
  --causal-proof runs/selfharness-final-ab/causal_proof.json
```

The claim card upgrades the overall Pass Rate and unattended-improvement fields only
when the proof's control/final Harness versions match the completed campaign lineage.

At 20 tasks × 2 repeats × 2 arms, the first stage requires 80 model-backed runs. It can
confirm a large effect; a small effect may require additional predeclared repeats. The
stopping rule must be fixed before results are inspected.

The existing 11/16 = 68.75% holdout remains a valid external capability result. It
becomes a causal Self-Harness uplift only after a matched parent-Harness arm exists on
the same frozen protocol.

## Machine-enforced claim states

[`docs/data/selfharness_scorecard.json`](data/selfharness_scorecard.json) keeps the
three headline questions separate:

- `self_harness_improves_overall_pass_rate`
- `multi_round_unattended_execution`
- `multi_round_unattended_improvement`
- `holdout_68_75_is_causal_uplift`

The unattended-execution value is now true; the Pass Rate and causal-uplift values
remain false with evidence-backed reasons. Tests prevent a
crossing-zero efficiency interval or a favorable-but-rejected candidate from silently
becoming a confirmed claim. Only a matched final holdout comparison can confirm causal
Pass Rate improvement.
