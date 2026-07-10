# HarnessForge

> A self-evolving coding-agent harness lab: observable, replayable, and evaluable.
> It mines weaknesses from failure traces, proposes harness-level diffs with predicted
> effects, and merges them only after passing a regression validation gate.

## Why

Harness engineering is about making non-deterministic agent systems reliable through
constraints, observability, and feedback loops — not about prompt tricks. HarnessForge
demonstrates the full loop:

```
run evals → collect traces → mine weaknesses → propose component diffs
    ↑                                                    ↓
merge & record calibration ← validation gate (paired regression runs)
```

Inspired by [Self-Harness (arXiv:2606.09498)](https://arxiv.org/abs/2606.09498),
scoped for a single developer and a <$100 API budget.

## Architecture

The harness is decomposed into **evolvable components** (`harness/`) and **fixed
runtime code** (`src/`). In v1, only declarative components are evolvable:

| Component | Evolvable (v1) | Role |
|---|---|---|
| `harness/system_prompt.md` | ✅ | Agent's system prompt |
| `harness/tool_descriptions.yaml` | ✅ | Tool specs shown to the model |
| `harness/loop_policy.yaml` | ✅ | Max steps, retries, test-failure behavior, termination |
| `src/.../context.py` | ❌ (params in loop_policy) | Context compaction |
| `src/.../tools.py` | ❌ | Tool implementations, patch apply/rollback |

Self-harness proposals are **small diffs against these components**, each carrying a
structured prediction (`expected_effect`, `risk`). After validation, the observed
effect is backfilled — accumulating a **proposal calibration table** (predicted vs.
actual improvement).

## Results

| Iteration | Pass rate (mean of 3 runs) | Cost/task | Merged proposals |
|---|---|---|---|
| Baseline | TBD | TBD | — |
| Round 1 | TBD | TBD | TBD |
| Round 2 | TBD | TBD | TBD |

## Quick start

```bash
pip install -e .
cp .env.example .env        # add your ANTHROPIC_API_KEY
python -m harnessforge.eval.runner --tasks tasks/ --out runs/baseline
python -m harnessforge.selfharness.mining --run runs/baseline
```

## Layout

```
harness/                 evolvable components (the "genome")
src/harnessforge/
  trace.py               JSONL trace schema + writer
  agent/                 agent loop, LLM client, tools
  sandbox/               Docker bash sandbox
  eval/                  task format + eval runner
  selfharness/           weakness mining, proposal gen, validation gate
tasks/                   eval task suite (terminal-bench style)
runs/, traces/           experiment outputs (gitignored)
```

## Design decisions

- **Declarative-only evolution in v1.** LLM-generated diffs to executable code fail
  as runtime crashes, which the pass-rate validation gate cannot catch. Code-level
  evolution is v2, behind component-level unit tests.
- **Paired validation, not aggregate pass rate.** With 15–30 tasks, single-run deltas
  are noise. The gate runs (failed tasks for the targeted pattern + a small regression
  set) × 2–3 repeats and compares per-task before/after.
- **Trace-first.** Every step is a JSONL event with tokens, cost, and exit reason.
  Mining, replay, and the dashboard all read the same schema.
