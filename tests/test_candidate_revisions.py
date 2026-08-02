"""Candidate revisions must be isolated and only the group winner may be promoted."""

from __future__ import annotations

import difflib
import json
import shutil
from pathlib import Path

import pytest

from harnessforge.config import EVOLVABLE_COMPONENTS, HarnessConfig
from harnessforge.selfharness import round as round_mod
from harnessforge.selfharness.schema import MiningReport, Proposal
from harnessforge.selfharness.validation import (
    ValidationVerdict,
    materialize_candidate,
    promote_proposal,
)

REPO_HARNESS = Path(__file__).parents[1] / "harness"


def _copy_harness(target: Path) -> Path:
    target.mkdir()
    for name in EVOLVABLE_COMPONENTS:
        shutil.copy2(REPO_HARNESS / name, target / name)
    return target


def _diff(old: str, new: str, name: str) -> str:
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{name}",
            tofile=f"b/{name}",
        )
    )


def _proposal(pid: str, old: str, new: str, group: str = "pattern-a") -> Proposal:
    return Proposal(
        proposal_id=pid,
        failure_pattern=group,
        candidate_group=group,
        component="system_prompt.md",
        diff=_diff(old, new, "system_prompt.md"),
        expected_effect=f"candidate {pid}",
        expected_pass_rate_delta=0.1,
    )


def test_materialized_candidate_does_not_mutate_parent(tmp_path):
    parent = _copy_harness(tmp_path / "parent")
    original = (parent / "system_prompt.md").read_text(encoding="utf-8")
    proposal = _proposal("p1", original, original + "\nCandidate one.\n")

    child = materialize_candidate(proposal, parent, tmp_path / "child")

    assert (parent / "system_prompt.md").read_text(encoding="utf-8") == original
    assert (child / "system_prompt.md").read_text(encoding="utf-8").endswith("Candidate one.\n")
    for name in EVOLVABLE_COMPONENTS[1:]:
        assert (child / name).read_bytes() == (parent / name).read_bytes()


def test_promote_archives_parent_and_changes_only_target(tmp_path):
    live = _copy_harness(tmp_path / "live")
    original = (live / "system_prompt.md").read_text(encoding="utf-8")
    policy_before = (live / "loop_policy.yaml").read_bytes()
    proposal = _proposal("winner", original, original + "\nWinning rule.\n")

    backup = promote_proposal(proposal, live)

    assert backup.parent == live / "_history"
    assert backup.read_text(encoding="utf-8") == original
    assert (live / "system_prompt.md").read_text(encoding="utf-8").endswith("Winning rule.\n")
    assert (live / "loop_policy.yaml").read_bytes() == policy_before


@pytest.mark.asyncio
async def test_round_promotes_only_best_sibling_from_shared_parent(tmp_path, monkeypatch):
    live = _copy_harness(tmp_path / "live")
    original = (live / "system_prompt.md").read_text(encoding="utf-8")
    weaker = _proposal("weaker", original, original + "\nWeaker rule.\n")
    winner = _proposal("winner", original, original + "\nWinner rule.\n")
    proposals = [weaker, winner]

    baseline = tmp_path / "baseline"
    baseline.mkdir()
    baseline_summary = {
        "pass_rate": 0.5,
        "total_cost_usd": 1.0,
        "harness_version": HarnessConfig.load(live).version,
    }
    (baseline / "summary.json").write_text(json.dumps(baseline_summary), encoding="utf-8")

    async def fake_mine(_baseline_dir):
        return MiningReport(
            run_dir=str(baseline),
            harness_version=baseline_summary["harness_version"],
            n_failed_runs=1,
            patterns=[],
        )

    async def fake_generate(*_args, **_kwargs):
        return proposals

    observed_parent_versions = []

    async def fake_validate(proposal, *_args, base_harness_dir, **_kwargs):
        observed_parent_versions.append(HarnessConfig.load(base_harness_dir).version)
        delta = 0.25 if proposal.proposal_id == "weaker" else 0.5
        proposal.accepted = True
        proposal.observed_pass_rate_delta = delta
        proposal.observed_cost_delta_pct = 0.0
        proposal.validation_notes = f"delta={delta}"
        return ValidationVerdict(proposal.proposal_id, True, delta, 0, 0.0, "isolated")

    async def fake_run_suite(*_args, **_kwargs):
        return {
            "pass_rate": 0.6,
            "total_cost_usd": 1.1,
            "harness_version": HarnessConfig.load(live).version,
        }

    monkeypatch.setattr(round_mod, "HARNESS_DIR", live)
    monkeypatch.setattr(round_mod, "mine", fake_mine)
    monkeypatch.setattr(round_mod, "generate", fake_generate)
    monkeypatch.setattr(round_mod, "validate", fake_validate)
    monkeypatch.setattr(round_mod, "run_suite", fake_run_suite)

    report = await round_mod.run_round(
        tmp_path / "tasks",
        tmp_path / "round",
        baseline,
        regression_tasks=["guard"],
        repeats=1,
        sandbox_kind="local",
    )

    assert observed_parent_versions == [
        baseline_summary["harness_version"],
        baseline_summary["harness_version"],
    ]
    final_prompt = (live / "system_prompt.md").read_text(encoding="utf-8")
    assert final_prompt.endswith("Winner rule.\n")
    assert "Weaker rule." not in final_prompt
    assert report["winners"] == ["winner"]
    assert len(list((live / "_history").iterdir())) == 1
