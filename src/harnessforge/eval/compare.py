"""Compare two runs (control vs treatment) on shared tasks: pass-rate delta AND
efficiency (steps, cost) deltas, each with a paired bootstrap CI.

Efficiency is reported because it is often the *measurable* win: continuous metrics
have much lower variance than binary pass/fail, so 'same pass rate, less cost'
reaches significance where a pass-rate lift cannot at the same sample size.

Usage:
    python -m harnessforge.eval.compare --control runs/tb_baseline --treatment runs/tb_selfverify
    # pool several dirs per arm to raise power:
    python -m harnessforge.eval.compare \\
        --control runs/tb_baseline runs/tb_base_extra \\
        --treatment runs/tb_selfverify runs/tb_selfverify_extra
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .stats import paired_bootstrap_continuous, paired_bootstrap_delta

SKIP = {"infra_error", "api_error"}


def _pool(run_dirs: list[Path], field: str):
    d: dict[str, list] = {}
    for rd in run_dirs:
        with (Path(rd) / "results.jsonl").open(encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                if r.get("exit_reason") in SKIP:
                    continue
                d.setdefault(r["task_id"], []).append(r[field])
    return d


def compare(control: list[Path], treatment: list[Path],
            task_ids: list[str] | None = None) -> dict:
    def restrict(d):
        return {k: v for k, v in d.items() if task_ids is None or k in task_ids}

    c_pass, t_pass = restrict(_pool(control, "passed")), restrict(_pool(treatment, "passed"))
    c_cost, t_cost = restrict(_pool(control, "cost_usd")), restrict(_pool(treatment, "cost_usd"))
    c_step, t_step = restrict(_pool(control, "steps")), restrict(_pool(treatment, "steps"))
    shared = sorted(set(c_pass) & set(t_pass))

    return {
        "n_shared_tasks": len(shared),
        "pass_rate": paired_bootstrap_delta(
            {k: c_pass[k] for k in shared}, {k: t_pass[k] for k in shared}),
        "cost": paired_bootstrap_continuous(
            {k: c_cost[k] for k in shared}, {k: t_cost[k] for k in shared}),
        "steps": paired_bootstrap_continuous(
            {k: c_step[k] for k in shared}, {k: t_step[k] for k in shared}),
    }


def _fmt(name, r, unit=""):
    sig = "significant" if (r["ci_low"] > 0) or (r["ci_high"] < 0) else "not significant (CI crosses 0)"
    extra = f"  ({r['pct_change']:+.1f}%)" if "pct_change" in r else ""
    return (f"  {name:10s} Δ {r['mean_delta']:+.3f}{unit}{extra}  "
            f"95% CI [{r['ci_low']:+.3f}, {r['ci_high']:+.3f}]  — {sig}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--control", nargs="+", type=Path, required=True)
    ap.add_argument("--treatment", nargs="+", type=Path, required=True)
    ap.add_argument("--task-ids", nargs="*", default=None)
    args = ap.parse_args()
    res = compare(args.control, args.treatment, args.task_ids)
    print(f"\nPaired comparison on {res['n_shared_tasks']} shared tasks:")
    print(_fmt("pass rate", res["pass_rate"]))
    print(_fmt("cost", res["cost"], " $"))
    print(_fmt("steps", res["steps"]))
    print()


if __name__ == "__main__":
    main()
