# HarnessForge

**A self-evolving coding-agent harness lab.** It runs an LLM agent against coding
tasks, mines failure patterns from execution traces, proposes *harness-level* changes
with predicted effects, and merges them only after a noise-aware regression gate —
then measures whether the change actually helped on an external benchmark.

Built to practice [harness engineering](https://martinfowler.com/articles/harness-engineering.html):
making non-deterministic agent systems reliable through constraints, observability,
and feedback loops — not prompt tricks.

<!-- CI badge goes here once Actions is enabled -->

---

## Results at a glance

**Terminal-Bench 2.0 subset** (20 pinned tasks, run in each task's real Docker image,
verified by TB's own reward check). Agent under test: `claude-haiku-4-5`. 25-step budget.

| | Pass rate | Notes |
|---|---|---|
| Baseline | **47.5%** (19/40, 2 repeats) | 36/40 runs exhausted the step budget without calling `finish` |

![TB baseline](docs/figures/tb_baseline.png)

**The headline isn't a number — it's a method.** Every proposed harness change is
measured, and the ones that turn out to be noise are rejected, including changes an
earlier, weaker gate had already accepted. Two worked examples:

| Intervention | Looked like | Held up under rigorous measurement? |
|---|---|---|
| *native round 1:* "reverify immediately after each patch" | small-sample validation: **+100%** on targeted tasks | ❌ controlled A/B: **≈0** (was noise) |
| *TB finish-fix:* "finish when you judge the task done" | −19% cost, agent stops on its own | ❌ pass rate **−0.10, 95% CI [−0.30, +0.10]** — the removed gate was load-bearing |

Full write-up with per-task data: [EXPERIMENTS.md](EXPERIMENTS.md).

---

## Why these design choices

**Headroom via budget, not a weak model.** Modern small models already solve
self-contained tasks: `claude-haiku-4-5` passed a 54-run native suite at 100%. Real
harness work isn't babysitting a dumb model — it's maximizing a strong model's
reliability under latency/step/cost constraints. So the agent is deliberately
constrained (tight step budget; a hard external benchmark) to push it into the regime
where *the harness* — not model capability — decides success.

![headroom](docs/figures/native_headroom.png)

**Declarative-only evolution (v1).** The harness is split into evolvable components
(`system_prompt.md`, `tool_descriptions.yaml`, `loop_policy.yaml`) and fixed runtime
code. Self-harness proposes small diffs to the declarative components only —
LLM-generated diffs to executable code fail as runtime crashes the pass-rate gate
can't catch.

**Statistical power is a first-class constraint.** Borderline tasks have true pass
rates around 0.3–0.7; at 2–3 repeats, per-task results flip freely. The validation
gate uses paired before/after repeats and an effect-size threshold, and every reported
number carries a bootstrap or Wilson interval.

---

## How it works

```
        ┌──────────────┐   traces    ┌─────────────────┐   patterns   ┌──────────────┐
  tasks │  eval runner │────────────▶│ weakness mining │─────────────▶│   proposal   │
   ─────▶ (agent loop, │  JSONL      │  (cluster fails │              │  generation  │
        │  sandbox)    │             │   from traces)  │              │ (component   │
        └──────▲───────┘             └─────────────────┘              │  diffs +     │
               │                                                      │  prediction) │
               │  merge if effect ≥ threshold & no regression         └──────┬───────┘
               │                                                             │
        ┌──────┴───────────────────────────────────────────────────────────▼──────┐
        │  validation gate: paired before/after on targeted + regression tasks,     │
        │  backfill observed effect  →  proposal calibration table                  │
        └───────────────────────────────────────────────────────────────────────────┘
```

The **agent loop** (`src/harnessforge/agent/loop.py`) is a from-scratch plan → tool-call
→ observation loop with retries, termination heuristics, context compaction, and a
budget guard. Tools: `bash`, `read_file`, `write_file`, `apply_patch`, `finish`, run in
a **Docker sandbox** (or a local sandbox for tests). Every step is a **JSONL trace event**
with tokens, cost, and exit reason — mining, replay, and reporting all read that schema.

---

## Layout

```
harness/                 evolvable components (the "genome")
src/harnessforge/
  agent/       loop, LLM client, tools, context compaction
  sandbox/     docker / local / terminal-bench sandboxes
  eval/        task format, runner, TB adapter+runner, stats (bootstrap/Wilson)
  selfharness/ weakness mining, proposal gen, validation gate, round driver
  trace.py     JSONL trace schema + writer
tasks/                   18 native tasks (bidirectionally verified)
scripts/                 figure generation, TB image pre-pull
docs/                    figures, data snapshots, dashboard
EXPERIMENTS.md           full experiment log + calibration table
```

## Quickstart

```bash
pip install -e ".[dev]"
cp .env.example .env            # add ANTHROPIC_API_KEY
pytest                          # 27 tests, mock-LLM end-to-end, no API cost

# native suite
python -m harnessforge.eval.runner --tasks tasks --out runs/baseline --repeats 3 --sandbox local

# Terminal-Bench subset (needs Docker; pre-pull images first)
python scripts/prepull_tb_images.py --tb-root ~/terminal-bench-2
python -m harnessforge.eval.tb_runner --tb-root ~/terminal-bench-2 --out runs/tb_baseline --repeats 2

# one self-harness iteration
python -m harnessforge.selfharness.round --tasks tasks --out runs/round1 \
    --regression-tasks t01_fix_off_by_one t05_fix_regex --repeats 3
```

## Reliability notes

Three production-style failures the harness hit and now handles, each surfaced by a
real run (see EXPERIMENTS.md): a retry loop with no timeout silently hung for 27 min on
a retired model ID; one task's API error crashed the whole eval suite via
`asyncio.gather`; flaky networks needed exponential backoff with jitter. All fixed in
fixed-runtime code and distinguished from genuine agent failures in the results.

*Terminal-Bench is © Laude Institute, Apache-2.0. This project vendors none of it; the
adapter reads a local clone.*
