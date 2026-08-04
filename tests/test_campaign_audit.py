from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from harnessforge.config import EVOLVABLE_COMPONENTS, HarnessConfig
from harnessforge.selfharness import round as round_mod

REPO_HARNESS = Path(__file__).parents[1] / "harness"


def _copy_harness(target: Path) -> Path:
    target.mkdir()
    for component in EVOLVABLE_COMPONENTS:
        shutil.copy2(REPO_HARNESS / component, target / component)
    return target


def _fake_report(round_number: int, harness_dir: Path, parent_version: str) -> dict:
    baseline_rate = 0.5 + 0.1 * (round_number - 1)
    final_rate = baseline_rate + 0.1
    return {
        "baseline": {
            "pass_rate": baseline_rate,
            "cost_usd": 1.0,
            "harness_version": parent_version,
        },
        "final": {
            "pass_rate": final_rate,
            "cost_usd": 1.0,
            "harness_version": HarnessConfig.load(harness_dir).version,
        },
        "n_candidates": 1,
        "n_patterns": 1,
        "n_winners": 1,
        "winners": [f"round-{round_number}-winner"],
        "calibration": [],
    }


def _complete_fake_round(out_dir: Path, memory, harness_dir: Path) -> dict:
    round_number = int(out_dir.name.removeprefix("round"))
    parent_version = HarnessConfig.load(harness_dir).version
    prompt = harness_dir / "system_prompt.md"
    prompt.write_text(
        prompt.read_text(encoding="utf-8") + f"\nRound {round_number}.\n",
        encoding="utf-8",
    )
    final = out_dir / "final"
    final.mkdir(parents=True)
    report = _fake_report(round_number, harness_dir, parent_version)
    (final / "summary.json").write_text(
        json.dumps(
            {
                "pass_rate": report["final"]["pass_rate"],
                "total_cost_usd": 1.0,
                "harness_version": report["final"]["harness_version"],
            }
        ),
        encoding="utf-8",
    )
    (out_dir / "memory.json").write_text(memory.model_dump_json(), encoding="utf-8")
    (out_dir / "round_report.json").write_text(
        json.dumps(report), encoding="utf-8"
    )
    return report


@pytest.mark.asyncio
async def test_campaign_persists_completed_autonomous_audit_without_mutating_repo(
    tmp_path, monkeypatch
):
    live = _copy_harness(tmp_path / "live")
    original = (live / "system_prompt.md").read_text(encoding="utf-8")

    async def fake_run_round(*_args, out_dir=None, memory=None, harness_dir=None, **_kwargs):
        # Positional parameters follow run_round(tasks_root, out_dir, ...).
        actual_out = Path(_args[1]) if out_dir is None else Path(out_dir)
        return _complete_fake_round(actual_out, memory, Path(harness_dir))

    monkeypatch.setattr(round_mod, "HARNESS_DIR", live)
    monkeypatch.setattr(round_mod, "run_round", fake_run_round)

    reports = await round_mod.run_campaign(
        tmp_path / "tasks",
        tmp_path / "campaign",
        None,
        regression_tasks=["guard"],
        n_rounds=2,
        repeats=2,
        sandbox_kind="local",
    )

    state = json.loads(
        (tmp_path / "campaign/campaign_report.json").read_text(encoding="utf-8")
    )
    assert len(reports) == 2
    assert state["status"] == "completed"
    assert state["rounds_completed"] == 2
    assert state["autonomous_round_transitions"] == 1
    assert state["repository_harness_mutated"] is False
    assert state["pass_rate_trajectory"] == [0.5, 0.6, 0.7]
    assert (live / "system_prompt.md").read_text(encoding="utf-8") == original


@pytest.mark.asyncio
async def test_campaign_records_interruption_and_resumes_from_last_completed_round(
    tmp_path, monkeypatch
):
    live = _copy_harness(tmp_path / "live")
    calls = {"round2": 0}

    async def flaky_run_round(*_args, out_dir=None, memory=None, harness_dir=None, **_kwargs):
        actual_out = Path(_args[1]) if out_dir is None else Path(out_dir)
        round_number = int(actual_out.name.removeprefix("round"))
        if round_number == 2 and calls["round2"] == 0:
            calls["round2"] += 1
            actual_out.mkdir(parents=True, exist_ok=True)
            raise RuntimeError("simulated process loss")
        return _complete_fake_round(actual_out, memory, Path(harness_dir))

    monkeypatch.setattr(round_mod, "HARNESS_DIR", live)
    monkeypatch.setattr(round_mod, "run_round", flaky_run_round)
    campaign = tmp_path / "campaign"

    with pytest.raises(RuntimeError, match="simulated process loss"):
        await round_mod.run_campaign(
            tmp_path / "tasks",
            campaign,
            None,
            regression_tasks=["guard"],
            n_rounds=2,
            repeats=2,
            sandbox_kind="local",
        )

    interrupted = json.loads(
        (campaign / "campaign_report.json").read_text(encoding="utf-8")
    )
    assert interrupted["status"] == "interrupted"
    assert interrupted["rounds_completed"] == 1
    assert interrupted["current_round"] == 2

    reports = await round_mod.run_campaign(
        tmp_path / "tasks",
        campaign,
        None,
        regression_tasks=["guard"],
        n_rounds=2,
        repeats=2,
        sandbox_kind="local",
        resume=True,
    )

    completed = json.loads(
        (campaign / "campaign_report.json").read_text(encoding="utf-8")
    )
    assert len(reports) == 2
    assert completed["status"] == "completed"
    assert completed["resume_count"] == 1
    assert (campaign / "round2-interrupted").exists()
    assert (campaign / "campaign_harness/round2-interrupted").exists()


@pytest.mark.asyncio
async def test_resume_recovers_a_committed_round_without_repeating_api_work(
    tmp_path, monkeypatch
):
    live = _copy_harness(tmp_path / "live")
    campaign = tmp_path / "campaign"
    calls = {"total": 0}

    class SimulatedHardKill(BaseException):
        pass

    async def killed_after_commit(
        *_args, out_dir=None, memory=None, harness_dir=None, **_kwargs
    ):
        actual_out = Path(_args[1]) if out_dir is None else Path(out_dir)
        calls["total"] += 1
        report = _complete_fake_round(actual_out, memory, Path(harness_dir))
        if actual_out.name == "round2":
            raise SimulatedHardKill
        return report

    monkeypatch.setattr(round_mod, "HARNESS_DIR", live)
    monkeypatch.setattr(round_mod, "run_round", killed_after_commit)

    with pytest.raises(SimulatedHardKill):
        await round_mod.run_campaign(
            tmp_path / "tasks",
            campaign,
            None,
            regression_tasks=["guard"],
            n_rounds=2,
            repeats=2,
            sandbox_kind="local",
        )

    async def must_not_rerun(*_args, **_kwargs):
        raise AssertionError("a fully committed round must be recovered, not rerun")

    monkeypatch.setattr(round_mod, "run_round", must_not_rerun)
    reports = await round_mod.run_campaign(
        tmp_path / "tasks",
        campaign,
        None,
        regression_tasks=["guard"],
        n_rounds=2,
        repeats=2,
        sandbox_kind="local",
        resume=True,
    )

    state = json.loads((campaign / "campaign_report.json").read_text())
    assert len(reports) == 2
    assert calls["total"] == 2
    assert state["status"] == "completed"
    assert state["resume_count"] == 1
    assert state["recovered_completed_rounds"] == 1
    assert not (campaign / "round2-interrupted").exists()


@pytest.mark.asyncio
async def test_campaign_budget_stops_before_next_round_and_can_resume_with_higher_ceiling(
    tmp_path, monkeypatch
):
    live = _copy_harness(tmp_path / "live")

    async def metered_round(*_args, out_dir=None, memory=None, harness_dir=None, **_kwargs):
        actual_out = Path(_args[1]) if out_dir is None else Path(out_dir)
        report = _complete_fake_round(actual_out, memory, Path(harness_dir))
        (actual_out / "meta_usage.json").write_text(
            json.dumps({
                "schema_version": 1,
                "total": {
                    "model_calls": 1,
                    "tokens_in": 100,
                    "tokens_out": 20,
                    "cost_usd": 1.0,
                },
            }),
            encoding="utf-8",
        )
        return report

    monkeypatch.setattr(round_mod, "HARNESS_DIR", live)
    monkeypatch.setattr(round_mod, "run_round", metered_round)
    campaign = tmp_path / "campaign"

    with pytest.raises(round_mod.CampaignBudgetExceeded, match="before campaign round 2"):
        await round_mod.run_campaign(
            tmp_path / "tasks",
            campaign,
            None,
            regression_tasks=["guard"],
            n_rounds=2,
            repeats=2,
            sandbox_kind="local",
            max_campaign_cost_usd=1.0,
        )

    stopped = json.loads((campaign / "campaign_report.json").read_text())
    assert stopped["status"] == "budget_exhausted"
    assert stopped["rounds_completed"] == 1
    assert stopped["budget"]["observed"]["total"]["cost_usd"] == 1.0
    assert stopped["budget"]["remaining_usd"] == 0.0

    reports = await round_mod.run_campaign(
        tmp_path / "tasks",
        campaign,
        None,
        regression_tasks=["guard"],
        n_rounds=2,
        repeats=2,
        sandbox_kind="local",
        resume=True,
        max_campaign_cost_usd=2.1,
    )

    completed = json.loads((campaign / "campaign_report.json").read_text())
    assert len(reports) == 2
    assert completed["status"] == "completed"
    assert completed["resume_count"] == 1
    assert completed["budget"]["observed"]["total"]["cost_usd"] == 2.0
    assert completed["budget"]["remaining_usd"] == 0.1
