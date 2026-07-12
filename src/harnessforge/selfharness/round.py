"""One full self-harness iteration:

    baseline eval -> weakness mining -> proposal generation
        -> validation gate per proposal (best predicted delta first)
        -> final full-suite eval -> round report

Usage:
    python -m harnessforge.selfharness.round \\
        --tasks tasks/ --out runs/round1 \\
        --baseline runs/baseline \\          # reuse existing baseline, or omit to run one
        --regression-tasks t01_fix_off_by_one t06_organize_logs \\
        --repeats 2 --sandbox docker

Outputs in --out:
    proposals.json      all proposals with predictions + backfilled observations
    verdicts.json       validation verdicts
    final/              full-suite eval with whatever was merged
    round_report.json   before/after summary — the numbers for your README table
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from ..eval.runner import run_suite
from .mining import mine
from .proposal import generate
from .schema import ProposalMemory
from .search import record_losers, select_best_per_group
from .validation import validate


async def run_round(tasks_root: Path, out_dir: Path, baseline_dir: Path | None,
                    regression_tasks: list[str], repeats: int = 2,
                    max_proposals: int = 6, sandbox_kind: str = "docker",
                    candidates_per_pattern: int = 3,
                    memory: ProposalMemory | None = None) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    memory = memory or ProposalMemory()

    # 1. Baseline (reuse if provided).
    if baseline_dir is None:
        baseline_dir = out_dir / "baseline"
        print(f"[round] running baseline -> {baseline_dir}")
        await run_suite(tasks_root, baseline_dir, repeats=repeats, sandbox_kind=sandbox_kind)
    baseline_summary = json.loads((baseline_dir / "summary.json").read_text(encoding="utf-8"))
    print(f"[round] baseline pass_rate={baseline_summary['pass_rate']}")

    # 2. Weakness mining (cached if already present).
    if not (baseline_dir / "mining_report.json").exists():
        print("[round] mining weaknesses...")
        report = await mine(baseline_dir)
    else:
        from .schema import MiningReport
        report = MiningReport.model_validate_json(
            (baseline_dir / "mining_report.json").read_text(encoding="utf-8"))
    print(f"[round] {len(report.patterns)} failure patterns")

    # 3. Proposals: multiple candidates per pattern, memory-aware, most promising first.
    proposals = await generate(report, max_proposals=max_proposals,
                               candidates_per_pattern=candidates_per_pattern, memory=memory)
    proposals.sort(key=lambda p: p.expected_pass_rate_delta, reverse=True)
    print(f"[round] {len(proposals)} candidate proposals pass pre-validation "
          f"({len({p.candidate_group for p in proposals})} patterns)")

    # 4. Validation gate, sequentially (each accepted change shifts the baseline).
    verdicts = []
    for prop in proposals:
        print(f"[round] validating {prop.proposal_id} -> {prop.component} "
              f"({prop.failure_pattern})")
        try:
            verdict = await validate(prop, baseline_dir, regression_tasks,
                                     tasks_root, out_dir / "validation", repeats=repeats,
                                     sandbox_kind=sandbox_kind)
        except Exception as e:
            # e.g. an earlier accepted proposal changed the same component and
            # this diff no longer applies. Record and move on — never lose the round.
            from .validation import ValidationVerdict
            verdict = ValidationVerdict(prop.proposal_id, False, 0.0, 0, 0.0,
                                        notes=f"validation error: {type(e).__name__}: {e}")
            prop.accepted = False
            prop.validation_notes = verdict.notes
        verdicts.append(verdict)
        print(f"[round]   {'ACCEPT' if verdict.accepted else 'reject'}: {prop.validation_notes}")

    # 4b. Keep the best candidate per pattern; fold the rest into memory.
    winners, losers = select_best_per_group(proposals)
    record_losers(memory, losers)
    print(f"[round] {len(winners)} winners, {len(losers)} recorded as memory "
          f"({len(memory.rejected)} total dead ends known)")

    (out_dir / "proposals.json").write_text(
        json.dumps([json.loads(p.model_dump_json()) for p in proposals], indent=2),
        encoding="utf-8")
    (out_dir / "verdicts.json").write_text(
        json.dumps([v.__dict__ for v in verdicts], indent=2), encoding="utf-8")

    # 5. Final full-suite eval with merged changes.
    print("[round] final full-suite eval...")
    final = await run_suite(tasks_root, out_dir / "final", repeats=repeats,
                            sandbox_kind=sandbox_kind)

    report_out = {
        "baseline": {"pass_rate": baseline_summary["pass_rate"],
                     "cost_usd": baseline_summary["total_cost_usd"],
                     "harness_version": baseline_summary["harness_version"]},
        "final": {"pass_rate": final["pass_rate"],
                  "cost_usd": final["total_cost_usd"],
                  "harness_version": final["harness_version"]},
        "n_candidates": len(proposals),
        "n_patterns": len({p.candidate_group for p in proposals}),
        "n_winners": len(winners),
        "winners": [p.proposal_id for p in winners],
        "calibration": [
            {"proposal_id": p.proposal_id,
             "candidate_group": p.candidate_group,
             "predicted_delta": p.expected_pass_rate_delta,
             "observed_delta": p.observed_pass_rate_delta,
             "accepted": p.accepted,
             "winner": p in winners}
            for p in proposals
        ],
    }
    (out_dir / "round_report.json").write_text(json.dumps(report_out, indent=2),
                                               encoding="utf-8")
    (out_dir / "memory.json").write_text(memory.model_dump_json(indent=2), encoding="utf-8")
    print(f"[round] done: pass_rate {baseline_summary['pass_rate']} -> {final['pass_rate']}")
    return report_out


async def run_campaign(tasks_root: Path, out_dir: Path, baseline_dir: Path | None,
                       regression_tasks: list[str], n_rounds: int = 3, repeats: int = 3,
                       max_proposals: int = 6, sandbox_kind: str = "docker",
                       candidates_per_pattern: int = 3) -> list[dict]:
    """Run several self-harness rounds. Memory of dead ends persists across rounds;
    each round's merged harness becomes the next round's starting point (its `final`
    eval becomes the next baseline), so improvements compound and mistakes aren't
    re-proposed."""
    out_dir.mkdir(parents=True, exist_ok=True)
    memory = ProposalMemory()
    reports = []
    prev_baseline = baseline_dir
    for i in range(1, n_rounds + 1):
        round_dir = out_dir / f"round{i}"
        print(f"\n===== CAMPAIGN ROUND {i}/{n_rounds} =====")
        rep = await run_round(tasks_root, round_dir, prev_baseline, regression_tasks,
                              repeats=repeats, max_proposals=max_proposals,
                              sandbox_kind=sandbox_kind,
                              candidates_per_pattern=candidates_per_pattern, memory=memory)
        reports.append(rep)
        # Next round starts from this round's merged-harness eval.
        prev_baseline = round_dir / "final"
    (out_dir / "campaign_report.json").write_text(json.dumps(reports, indent=2),
                                                  encoding="utf-8")
    trajectory = [r["baseline"]["pass_rate"] for r in reports] + [reports[-1]["final"]["pass_rate"]]
    print(f"\n[campaign] pass-rate trajectory: {trajectory}")
    return reports


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", type=Path, default=Path("tasks"))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--baseline", type=Path, default=None)
    ap.add_argument("--regression-tasks", nargs="+", required=True)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--max-proposals", type=int, default=6)
    ap.add_argument("--candidates-per-pattern", type=int, default=3)
    ap.add_argument("--rounds", type=int, default=1, help=">1 runs a multi-round campaign")
    ap.add_argument("--sandbox", choices=["docker", "local"], default="docker")
    args = ap.parse_args()
    if args.rounds > 1:
        asyncio.run(run_campaign(args.tasks, args.out, args.baseline, args.regression_tasks,
                                 n_rounds=args.rounds, repeats=args.repeats,
                                 max_proposals=args.max_proposals, sandbox_kind=args.sandbox,
                                 candidates_per_pattern=args.candidates_per_pattern))
    else:
        asyncio.run(run_round(args.tasks, args.out, args.baseline, args.regression_tasks,
                              args.repeats, args.max_proposals, args.sandbox,
                              args.candidates_per_pattern))


if __name__ == "__main__":
    main()
