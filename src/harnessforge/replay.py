"""Pretty-print a recorded run trace, step by step — "show me how this failure
happened." Observability is the point of a harness; this reads the same JSONL
schema everything else does.

Usage:
    python -m harnessforge.replay runs/tb_baseline/traces/<run_id>.jsonl
    python -m harnessforge.replay runs/tb_baseline/traces/<run_id>.jsonl --full
    python -m harnessforge.replay --run-dir runs/tb_baseline --grep max_steps
"""

from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path
from typing import Any

# ANSI colors (fall back to plain if not a tty)
C = {"dim": "\033[2m", "b": "\033[1m", "cyan": "\033[36m", "green": "\033[32m",
     "red": "\033[31m", "yellow": "\033[33m", "reset": "\033[0m"}


def _c(color: str, s: str, enable: bool) -> str:
    return f"{C[color]}{s}{C['reset']}" if enable else s


def _clip(s: str, n: int, full: bool) -> str:
    s = s.replace("\n", " ⏎ ")
    return s if full or len(s) <= n else s[:n] + "…"


def replay(path: Path, full: bool = False, color: bool = True) -> dict[str, Any]:
    events = [json.loads(line) for line in Path(path).open(encoding="utf-8") if line.strip()]
    clip = 4000 if full else 140

    header = next((e for e in events if e["event_type"] == "run_start"), None)
    end = next((e for e in events if e["event_type"] == "termination"), None)
    task = events[0]["task_id"] if events else "?"

    print(_c("b", f"\n━━ {task} ", color) + _c("dim", f"({Path(path).name})", color))
    if header:
        p = header["payload"]
        print(_c("dim", f"   harness={p.get('harness_version','?')} "
                        f"model={p.get('model','?')}", color))

    iters = 0
    for e in events:
        t, p = e["event_type"], e["payload"]
        if t == "llm_request":
            iters += 1
            print(_c("dim", f"\n  ┌─ step {iters}", color))
        elif t == "llm_response":
            if p.get("text"):
                print("  │ " + _c("cyan", "think ", color) + _clip(p["text"], clip, full))
        elif t == "tool_call":
            tool = p.get("tool", "?")
            inp = _clip(json.dumps(p.get("input", {}), ensure_ascii=False), clip, full)
            print("  │ " + _c("yellow", f"call  {tool} ", color) + _c("dim", inp, color))
        elif t == "tool_result":
            mark = _c("red", "✗", color) if p.get("error") else _c("green", "✓", color)
            print(f"  │   {mark} " + _c("dim", _clip(str(p.get("output", "")), clip, full), color))
        elif t == "test_run":
            mark = _c("green", "PASS", color) if p.get("passed") else _c("red", "FAIL", color)
            print("  │ " + _c("b", f"test  {mark}", color))
        elif t == "validation_error":
            print("  │ " + _c("red", f"reject {p.get('tool')} ", color)
                  + _c("dim", _clip(str(p.get("error", "")), clip, full), color))
        elif t == "memory_write":
            print("  │ " + _c("cyan", f"note  {p.get('key')} ", color)
                  + _c("dim", _clip(str(p.get("content", "")), clip, full), color))
        elif t == "compaction":
            print("  │ " + _c("dim", f"compaction {p.get('tokens_before')}→"
                                     f"{p.get('tokens_after')} tok", color))

    if end:
        er = end["payload"].get("exit_reason", "?")
        col = "green" if er.startswith("finished") else "red"
        print(_c("b", "\n  └─ ", color) + _c(col, er, color)
              + _c("dim", f"  ({iters} steps)", color))
    print()
    return {"task": task, "steps": iters,
            "exit_reason": end["payload"].get("exit_reason") if end else None}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("trace", nargs="?", type=Path, help="path to a .jsonl trace")
    ap.add_argument("--run-dir", type=Path, help="replay every trace in a run's traces/ dir")
    ap.add_argument("--grep", help="with --run-dir, only replay traces whose exit_reason matches")
    ap.add_argument("--full", action="store_true", help="don't truncate outputs")
    ap.add_argument("--no-color", action="store_true")
    args = ap.parse_args()
    color = not args.no_color

    if args.run_dir:
        for f in sorted(glob.glob(str(args.run_dir / "traces" / "*.jsonl"))):
            if args.grep:
                events = [json.loads(x) for x in open(f) if x.strip()]
                end = next((e for e in events if e["event_type"] == "termination"), None)
                if not end or args.grep not in end["payload"].get("exit_reason", ""):
                    continue
            replay(Path(f), full=args.full, color=color)
    elif args.trace:
        replay(args.trace, full=args.full, color=color)
    else:
        ap.error("provide a trace path or --run-dir")


if __name__ == "__main__":
    main()
