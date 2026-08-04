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
import os
import shutil
from pathlib import Path
from typing import Any

from ..config import HARNESS_DIR, HarnessConfig
from ..eval.counterfactual import _write_json_atomic
from ..eval.runner import run_suite
from .mining import mine
from .proposal import generate
from .schema import ProposalMemory
from .search import record_losers, select_best_per_group
from .validation import promote_proposal, validate


async def run_round(tasks_root: Path, out_dir: Path, baseline_dir: Path | None,
                    regression_tasks: list[str], repeats: int = 2,
                    max_proposals: int = 6, sandbox_kind: str = "docker",
                    candidates_per_pattern: int = 3,
                    memory: ProposalMemory | None = None,
                    harness_dir: Path | None = None) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    memory = memory or ProposalMemory()
    harness_dir = Path(harness_dir or HARNESS_DIR)

    # 1. Baseline (reuse if provided).
    if baseline_dir is None:
        baseline_dir = out_dir / "baseline"
        print(f"[round] running baseline -> {baseline_dir}")
        await run_suite(
            tasks_root,
            baseline_dir,
            repeats=repeats,
            sandbox_kind=sandbox_kind,
            harness_dir=harness_dir,
        )
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

    # 4. Validate sibling candidates against the SAME immutable parent revision.
    # Promote only the best accepted candidate in each pattern group; the next
    # group then starts from that promoted revision so improvements can compound.
    grouped: dict[str, list] = {}
    for prop in proposals:
        grouped.setdefault(prop.candidate_group or prop.proposal_id, []).append(prop)

    verdicts = []
    winners = []
    losers = []
    for group, candidates in grouped.items():
        parent_version = HarnessConfig.load(harness_dir).version
        print(f"[round] candidate group {group}: {len(candidates)} siblings "
              f"from parent {parent_version}")
        for prop in candidates:
            print(f"[round] validating {prop.proposal_id} -> {prop.component} "
                  f"({prop.failure_pattern})")
            try:
                verdict = await validate(
                    prop, baseline_dir, regression_tasks,
                    tasks_root, out_dir / "validation", repeats=repeats,
                    sandbox_kind=sandbox_kind, base_harness_dir=harness_dir,
                )
            except Exception as e:
                from .validation import ValidationVerdict
                verdict = ValidationVerdict(
                    prop.proposal_id, False, 0.0, 0, 0.0,
                    notes=f"validation error: {type(e).__name__}: {e}",
                )
                prop.accepted = False
                prop.validation_notes = verdict.notes
            verdicts.append(verdict)
            print(f"[round]   {'eligible' if verdict.accepted else 'reject'}: "
                  f"{prop.validation_notes}")

        group_winners, group_losers = select_best_per_group(candidates)
        if group_winners:
            winner = group_winners[0]
            promote_proposal(winner, harness_dir)
            winners.append(winner)
            print(f"[round] promoted {winner.proposal_id}; "
                  f"harness={HarnessConfig.load(harness_dir).version}")
        losers.extend(group_losers)

    # 4b. Fold every rejected/also-ran candidate into cross-round memory.
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
                            sandbox_kind=sandbox_kind, harness_dir=harness_dir)

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
    _write_json_atomic(out_dir / "round_report.json", report_out)
    _write_json_atomic(out_dir / "memory.json", memory.model_dump(mode="json"))
    print(f"[round] done: pass_rate {baseline_summary['pass_rate']} -> {final['pass_rate']}")
    return report_out


def _copy_harness_revision(source: Path, target: Path) -> None:
    """Materialize an isolated campaign revision without mutating the repository."""
    source = Path(source)
    target = Path(target)
    target.mkdir(parents=True, exist_ok=False)
    from ..config import EVOLVABLE_COMPONENTS

    for component in EVOLVABLE_COMPONENTS:
        shutil.copy2(source / component, target / component)


def _next_archive_path(path: Path) -> Path:
    """Return a stable, non-destructive archive name across repeated resumes."""
    candidate = path.with_name(f"{path.name}-interrupted")
    suffix = 2
    while candidate.exists():
        candidate = path.with_name(f"{path.name}-interrupted-{suffix}")
        suffix += 1
    return candidate


def _campaign_state(
    *,
    status: str,
    protocol: dict[str, Any],
    reports: list[dict[str, Any]],
    resume_count: int,
    recovered_completed_rounds: int,
    current_round: int | None,
    error: str | None = None,
) -> dict[str, Any]:
    trajectory = []
    if reports:
        trajectory = [report["baseline"]["pass_rate"] for report in reports]
        trajectory.append(reports[-1]["final"]["pass_rate"])
    return {
        "schema_version": 1,
        "experiment": "autonomous_self_harness_campaign",
        "status": status,
        "protocol": protocol,
        "rounds_completed": len(reports),
        "current_round": current_round,
        "resume_count": resume_count,
        "recovered_completed_rounds": recovered_completed_rounds,
        "autonomous_round_transitions": max(0, len(reports) - 1),
        "repository_harness_mutated": False,
        "pass_rate_trajectory": trajectory,
        "round_reports": reports,
        "error": error,
    }


async def run_campaign(tasks_root: Path, out_dir: Path, baseline_dir: Path | None,
                       regression_tasks: list[str], n_rounds: int = 3, repeats: int = 3,
                       max_proposals: int = 6, sandbox_kind: str = "docker",
                       candidates_per_pattern: int = 3,
                       resume: bool = False) -> list[dict]:
    """Run several self-harness rounds. Memory of dead ends persists across rounds;
    each round's merged harness becomes the next round's starting point (its `final`
    eval becomes the next baseline), so improvements compound and mistakes aren't
    re-proposed."""
    out_dir = Path(out_dir)
    if n_rounds <= 0:
        raise ValueError("n_rounds must be positive")
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "campaign_report.json"
    protocol = {
        "rounds_planned": n_rounds,
        "repeats": repeats,
        "max_proposals_per_round": max_proposals,
        "candidates_per_pattern": candidates_per_pattern,
        "sandbox": sandbox_kind,
        "regression_tasks": sorted(regression_tasks),
        "initial_baseline": str(Path(baseline_dir).resolve()) if baseline_dir else None,
        "execution": "isolated_campaign_harness; automatic transitions between rounds",
    }

    reports: list[dict[str, Any]] = []
    memory = ProposalMemory()
    resume_count = 0
    recovered_completed_rounds = 0
    if report_path.exists():
        if not resume:
            raise FileExistsError(f"campaign report already exists: {report_path}")
        prior = json.loads(report_path.read_text(encoding="utf-8"))
        if prior["protocol"] != protocol:
            raise ValueError("resume protocol does not match the saved campaign")
        if prior["status"] == "completed":
            return list(prior["round_reports"])
        reports = list(prior["round_reports"])
        resume_count = int(prior.get("resume_count", 0)) + 1
        recovered_completed_rounds = int(
            prior.get("recovered_completed_rounds", 0)
        )
        if reports:
            memory = ProposalMemory.model_validate_json(
                (out_dir / f"round{len(reports)}" / "memory.json").read_text(
                    encoding="utf-8"
                )
            )

    harness_root = out_dir / "campaign_harness"
    initial_harness = harness_root / "round0"
    if not initial_harness.exists():
        harness_root.mkdir(parents=True, exist_ok=True)
        _copy_harness_revision(HARNESS_DIR, initial_harness)

    # A hard process loss can happen after run_round atomically commits its own
    # artifacts but before the parent campaign report is updated. Recover that
    # completed round instead of archiving it and paying for the same API calls
    # again. Only a fully consistent artifact set is eligible for recovery.
    if resume:
        while len(reports) < n_rounds:
            round_number = len(reports) + 1
            round_dir = out_dir / f"round{round_number}"
            working_harness = harness_root / f"round{round_number}"
            round_report_path = round_dir / "round_report.json"
            memory_path = round_dir / "memory.json"
            final_summary_path = round_dir / "final" / "summary.json"
            required = (
                round_report_path,
                memory_path,
                final_summary_path,
                working_harness,
            )
            if not all(path.exists() for path in required):
                break
            recovered_report = json.loads(
                round_report_path.read_text(encoding="utf-8")
            )
            final_summary = json.loads(
                final_summary_path.read_text(encoding="utf-8")
            )
            harness_version = HarnessConfig.load(working_harness).version
            report_version = recovered_report.get("final", {}).get(
                "harness_version"
            )
            summary_version = final_summary.get("harness_version")
            expected_parent_version = (
                reports[-1]["final"]["harness_version"]
                if reports
                else HarnessConfig.load(initial_harness).version
            )
            recovered_parent_version = recovered_report.get("baseline", {}).get(
                "harness_version"
            )
            if report_version != harness_version or summary_version != harness_version:
                raise ValueError(
                    f"completed round {round_number} artifacts disagree on "
                    "harness version"
                )
            if recovered_parent_version != expected_parent_version:
                raise ValueError(
                    f"completed round {round_number} does not descend from the "
                    "recorded parent harness"
                )
            reports.append(recovered_report)
            memory = ProposalMemory.model_validate_json(
                memory_path.read_text(encoding="utf-8")
            )
            recovered_completed_rounds += 1

    if baseline_dir is not None and not reports:
        baseline_summary = json.loads(
            (Path(baseline_dir) / "summary.json").read_text(encoding="utf-8")
        )
        if baseline_summary["harness_version"] != HarnessConfig.load(initial_harness).version:
            raise ValueError(
                "baseline harness version does not match the campaign parent revision"
            )

    _write_json_atomic(
        report_path,
        _campaign_state(
            status="running",
            protocol=protocol,
            reports=reports,
            resume_count=resume_count,
            recovered_completed_rounds=recovered_completed_rounds,
            current_round=len(reports) + 1 if len(reports) < n_rounds else None,
        ),
    )

    if len(reports) == n_rounds:
        _write_json_atomic(
            report_path,
            _campaign_state(
                status="completed",
                protocol=protocol,
                reports=reports,
                resume_count=resume_count,
                recovered_completed_rounds=recovered_completed_rounds,
                current_round=None,
            ),
        )
        trajectory = [r["baseline"]["pass_rate"] for r in reports] + [
            reports[-1]["final"]["pass_rate"]
        ]
        print(f"\n[campaign] recovered pass-rate trajectory: {trajectory}")
        return reports

    prev_baseline = (
        out_dir / f"round{len(reports)}" / "final" if reports else baseline_dir
    )
    for i in range(len(reports) + 1, n_rounds + 1):
        round_dir = out_dir / f"round{i}"
        if round_dir.exists():
            archived_round = _next_archive_path(round_dir)
            os.replace(round_dir, archived_round)
        parent_harness = harness_root / f"round{i - 1}"
        working_harness = harness_root / f"round{i}"
        if working_harness.exists():
            archived = _next_archive_path(working_harness)
            os.replace(working_harness, archived)
        _copy_harness_revision(parent_harness, working_harness)
        print(f"\n===== CAMPAIGN ROUND {i}/{n_rounds} =====")
        try:
            rep = await run_round(
                tasks_root,
                round_dir,
                prev_baseline,
                regression_tasks,
                repeats=repeats,
                max_proposals=max_proposals,
                sandbox_kind=sandbox_kind,
                candidates_per_pattern=candidates_per_pattern,
                memory=memory,
                harness_dir=working_harness,
            )
        except Exception as exc:
            _write_json_atomic(
                report_path,
                _campaign_state(
                    status="interrupted",
                    protocol=protocol,
                    reports=reports,
                    resume_count=resume_count,
                    recovered_completed_rounds=recovered_completed_rounds,
                    current_round=i,
                    error=f"{type(exc).__name__}: {exc}",
                ),
            )
            raise
        reports.append(rep)
        prev_baseline = round_dir / "final"
        _write_json_atomic(
            report_path,
            _campaign_state(
                status="running" if i < n_rounds else "completed",
                protocol=protocol,
                reports=reports,
                resume_count=resume_count,
                recovered_completed_rounds=recovered_completed_rounds,
                current_round=i + 1 if i < n_rounds else None,
            ),
        )
    trajectory = [r["baseline"]["pass_rate"] for r in reports] + [
        reports[-1]["final"]["pass_rate"]
    ]
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
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--sandbox", choices=["docker", "local"], default="docker")
    args = ap.parse_args()
    if args.rounds > 1:
        asyncio.run(run_campaign(args.tasks, args.out, args.baseline, args.regression_tasks,
                                 n_rounds=args.rounds, repeats=args.repeats,
                                 max_proposals=args.max_proposals, sandbox_kind=args.sandbox,
                                 candidates_per_pattern=args.candidates_per_pattern,
                                 resume=args.resume))
    else:
        asyncio.run(run_round(args.tasks, args.out, args.baseline, args.regression_tasks,
                              args.repeats, args.max_proposals, args.sandbox,
                              args.candidates_per_pattern))


if __name__ == "__main__":
    main()
