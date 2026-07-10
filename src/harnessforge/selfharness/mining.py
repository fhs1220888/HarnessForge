"""Weakness mining: cluster failure patterns from execution traces.

Two stages:
1. Mechanical pre-clustering (free): group failed runs by exit_reason and
   cheap trace statistics (steps, tool-error rate, tests_ran).
2. LLM analysis (cheap-ish): for each cluster, feed compressed trace excerpts
   to the miner model and ask for structured FailurePatterns.

Usage:
    python -m harnessforge.selfharness.mining --run runs/baseline
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from ..trace import load_trace
from .schema import FailurePattern, MiningReport

MINING_PROMPT = """\
You are analyzing execution traces of a coding agent that FAILED its tasks.
Below are compressed excerpts from several failed runs sharing exit_reason={exit_reason}.

For each distinct failure pattern you can identify, output a JSON object:
{{"pattern_id": "<kebab-case-slug>", "description": "<1-2 sentences>",
  "evidence_runs": ["<run_id>", ...], "example_excerpt": "<short quote from a trace>"}}

Output a JSON array only. Identify at most 3 patterns. Be specific: point to the
agent's *behavior* (e.g. "edits files without reading the failing traceback"),
not generic causes (e.g. "the task was hard").

Excerpts:
{excerpts}
"""


def compress_trace(events: list[dict[str, Any]], max_chars: int = 3000) -> str:
    """One line per salient event: tool calls, test runs, termination."""
    lines = []
    for ev in events:
        t, p = ev["event_type"], ev["payload"]
        if t == "tool_call":
            lines.append(f"[{ev['step']}] CALL {p.get('tool')}: "
                         f"{json.dumps(p.get('input', {}))[:150]}")
        elif t == "tool_result" and p.get("error"):
            lines.append(f"[{ev['step']}] ERROR ({p.get('tool')}): {p.get('output', '')[:150]}")
        elif t == "test_run":
            lines.append(f"[{ev['step']}] TEST {'PASS' if p.get('passed') else 'FAIL'}: "
                         f"{p.get('output', '')[:150]}")
        elif t == "termination":
            lines.append(f"[{ev['step']}] END: {p.get('exit_reason')}")
    text = "\n".join(lines)
    return text[:max_chars]


def precluster(run_dir: Path) -> dict[str, list[dict[str, Any]]]:
    """Group failed outcomes by exit_reason; attach their traces."""
    clusters: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with (run_dir / "results.jsonl").open(encoding="utf-8") as f:
        for line in f:
            o = json.loads(line)
            if o["passed"]:
                continue
            trace_path = run_dir / "traces" / f"{o['run_id']}.jsonl"
            events = load_trace(trace_path) if trace_path.exists() else []
            clusters[o["exit_reason"]].append({"outcome": o, "events": events})
    return dict(clusters)


async def mine(run_dir: Path) -> MiningReport:
    clusters = precluster(run_dir)
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    report = MiningReport(
        run_dir=str(run_dir),
        harness_version=summary["harness_version"],
        n_failed_runs=sum(len(v) for v in clusters.values()),
    )

    from ..agent.llm import LLMClient  # miner may use a stronger model
    import os
    miner = LLMClient(model=os.environ.get("MINER_MODEL"))

    for exit_reason, runs in clusters.items():
        excerpts = "\n\n---\n\n".join(
            f"run_id={r['outcome']['run_id']} task={r['outcome']['task_id']}\n"
            + compress_trace(r["events"])
            for r in runs[:6]  # cap excerpts per cluster to control cost
        )
        resp = await miner.complete(
            system="You are a rigorous agent-harness failure analyst.",
            messages=[{"role": "user", "content": MINING_PROMPT.format(
                exit_reason=exit_reason, excerpts=excerpts)}],
        )
        try:
            raw = json.loads(resp.text[resp.text.find("[") : resp.text.rfind("]") + 1])
            for item in raw:
                item["frequency"] = len(item.get("evidence_runs", []))
                report.patterns.append(FailurePattern(**item))
        except (json.JSONDecodeError, ValueError):
            pass  # TODO: retry with a repair prompt

    out = run_dir / "mining_report.json"
    out.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return report


def main() -> None:
    import asyncio
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, required=True)
    args = ap.parse_args()
    report = asyncio.run(mine(args.run))
    print(report.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
