# My agent-harness validation gate merged pure noise. Here's what it taught me.

*Draft — for a personal blog / dev.to. ~1,400 words. Tone: honest engineering post-mortem.*

I built a system that lets an AI coding agent improve its own harness — the layer of
prompts, tool descriptions, loop policy, and guardrails that wraps the model. The idea,
following recent "self-harness" work, is a loop: run the agent on a suite of tasks, mine
the failures, propose small changes to the harness, and merge the ones that help.

The first change my system proposed and accepted made the benchmark *worse*. That was
the most useful thing that happened, and this post is about why.

## The setup

The harness is split into two halves. One half is fixed runtime code: the agent loop,
the Docker sandbox, the trace writer. The other half — the part the system is allowed to
evolve — is three declarative files: a system prompt, a set of tool descriptions, and a
loop policy (step budget, when to run tests, when to stop). Self-improvement proposes
*diffs to those three files*, never to the executable code, because an LLM-generated diff
to real code fails as a runtime crash that a pass-rate metric can't see.

Every proposal has to carry a prediction:

```json
{
  "failure_pattern": "agent applies a patch but never re-runs the tests",
  "component": "system_prompt.md",
  "change": "after any apply_patch, the next action must be the test command",
  "expected_pass_rate_delta": 0.08
}
```

A validation gate then runs the harness before and after the change on the tasks the
pattern came from plus a small regression set, and merges only if things improve.

## The bug that wasn't a bug

I gave the agent a deliberately tight step budget so it would actually fail sometimes —
you can't study harness improvements on a suite the model already aces (mine did: 100%
on 54 native runs before I tightened the budget). At 8 steps, the native suite dropped to
67%. Good, now there's headroom.

Mining the failures surfaced a clean pattern: *the agent edits a file to fix a failing
test, then declares victory without re-running the test.* The proposed fix was a one-line
rule: after any `apply_patch`, the next tool call must be the test command. Predicted
effect: +8 points. The validation gate ran it and reported **+100%** on the targeted
tasks — every previously-failing target now passed. Merged.

Then I ran the full suite. Pass rate went **down**, 67% → 58%.

## Where the +100% came from

The targeted set was tiny — a couple of tasks, two repeats each. On borderline tasks,
`claude-haiku-4-5` has a true pass rate somewhere around 0.3–0.7. At two samples, a task
flips between "passed twice" and "failed twice" all the time, for reasons that have
nothing to do with my change. The gate saw two targeted tasks go from fail→pass and
called it a +100% improvement. It was measuring noise and rounding it up to a triumph.

To check, I ran a controlled A/B: the exact same change, but on nine borderline tasks,
three repeats per arm, comparing per-task. The paired delta was ≈0, with a bootstrap
95% confidence interval that comfortably straddled zero. The task that had "justified"
the merge — the one that went fail→pass in validation — went pass→fail in the A/B.

The rule wasn't good or bad. It was nothing. And my gate had happily merged nothing.

## The second lesson: gates that look pointless can be load-bearing

I took the system to a real benchmark — a subset of Terminal-Bench, where each task runs
in its own Docker image and is graded by a hidden verifier the agent never sees. Baseline:
47.5%. But the striking number was different: **36 of 40 runs used up the entire step
budget without ever calling `finish`.** The agent just... never stopped. Even tasks it
*passed* were tasks where it did the work and then kept flailing until the budget ran out.

The reason turned out to be structural. On my native suite the agent confirms success by
running pytest and seeing green, then finishes. On Terminal-Bench there's no visible test
— verification is external and hidden — so the agent is never confident it's done. It
keeps poking.

The obvious fix: tell the agent to recognize completion and finish, and remove the
`run_tests_before_finish` gate that was clearly misfiring here (there's no test for it to
gate on). I ran the A/B. The agent did start finishing — `finish` calls went 0→8 out of
20, average steps dropped, cost fell 19%. And pass rate went from 0.50 to 0.40.

I'd removed a gate that looked useless and it turned out to be doing real work: it had
been *suppressing premature completion*. On a benchmark where the agent can't verify
itself, "finish when you think you're done" means "finish when you *guess* you're done,"
and the guess is often wrong. The budget-burning I was trying to eliminate was partly the
agent grinding its way to a correct answer it couldn't confirm. Buying efficiency by
telling it to stop traded away correctness. The 95% CI on the pass-rate drop crossed zero,
so I won't overclaim it hurt — but it certainly didn't help, and the mechanism is clear.

## What I actually changed

Not the harness — the *gate*. Two rules now:

1. **Effect-size threshold, not any positive delta.** A change merges only if the paired
   improvement clears +0.25, not merely >0. Noise rarely clears a real bar.
2. **Report intervals, always.** Every number in the repo — pass rates, deltas — carries a
   Wilson or bootstrap interval. A point estimate from three noisy runs is a vibe, not a
   result.

And I keep a **calibration table**: for every proposal, predicted effect vs. what
rigorous measurement actually found. After two entries it reads: predicted +0.08 /
small-sample +1.00 / controlled ≈0, and predicted +0.08 / controlled −0.10. Both say the
same thing. The table is the most honest artifact in the project.

## Why this is the whole point of harness engineering

It would have been easy to write the version of this post where the graph goes up and to
the right. Ship a prompt tweak, show a +10-point bar, call it a self-improving agent. The
self-harness paper I was following reports gains up to +60% — on weak open-source models
with lots of failures to fix and, presumably, enough statistical power to trust the deltas.

But the job I'm practicing for isn't "make the number go up." Agent harnesses in
production are judged on reliability, and reliability engineering on non-deterministic
systems is mostly about *not fooling yourself*: knowing when a delta is real, which
guardrails are load-bearing, and how much of an improvement is just the dice landing your
way this time. My validation gate fooled itself on the very first try. Catching that — and
rebuilding the gate so it can't happen again — taught me more than a green graph would
have.

---

*Code, full experiment log, and the calibration table: [github.com/fhs1220888/HarnessForge](https://github.com/fhs1220888/HarnessForge)*

<!-- TODO before publishing:
  - confirm the round-1 native numbers (67%→58%) against runs/round1
  - add the tb_baseline per-task figure
  - soften/verify any claim you can't reproduce
  - 2nd post idea: "Building the harness itself" (architecture + trace/replay design)
-->
