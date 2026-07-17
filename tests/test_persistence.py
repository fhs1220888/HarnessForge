"""Crash-safe persistence + resume (eval/persistence.py, wired into runner.py).

The scenario under test is the one that actually hurts: a suite run crashes
mid-flight after real API spend. Completed outcomes must already be on disk,
and --resume must re-run only what's missing.
"""

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from harnessforge.eval import runner as runner_mod
from harnessforge.eval.persistence import ResultSink
from harnessforge.eval.runner import TaskOutcome, run_suite

REPO = Path(__file__).parents[1]


def _outcome(task_id="t1", repeat=0, exit_reason="finished_done",
             version="v1", passed=True) -> TaskOutcome:
    return TaskOutcome(task_id=task_id, repeat=repeat, run_id=f"{task_id}-r{repeat}",
                       passed=passed, exit_reason=exit_reason, steps=3, cost_usd=0.01,
                       tokens=100, harness_version=version)


def _read(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


# ---- ResultSink unit tests ---------------------------------------------------

def test_record_hits_disk_immediately(tmp_path):
    sink = ResultSink(tmp_path)
    sink.record(_outcome("t1", 0))
    # No flush/close step: the row must already be on disk (crash-safety).
    assert _read(sink.path) == sink.rows()
    sink.record(_outcome("t2", 0))
    assert len(_read(sink.path)) == 2


def test_fresh_run_truncates_stale_file(tmp_path):
    (tmp_path / "results.jsonl").write_text('{"stale": true}\n')
    sink = ResultSink(tmp_path, resume=False)
    assert sink.rows() == [] and _read(sink.path) == []


def test_resume_keeps_completed_and_skips_them(tmp_path):
    old = ResultSink(tmp_path)
    old.record(_outcome("t1", 0))
    old.record(_outcome("t1", 1))
    sink = ResultSink(tmp_path, resume=True)
    assert sink.n_resumed == 2
    assert sink.is_done("t1", 0) and sink.is_done("t1", 1)
    assert not sink.is_done("t1", 2) and not sink.is_done("t2", 0)


def test_resume_drops_infra_rows_for_rerun(tmp_path):
    old = ResultSink(tmp_path)
    old.record(_outcome("t1", 0))
    old.record(_outcome("t2", 0, exit_reason="api_error", passed=False))
    old.record(_outcome("t3", 0, exit_reason="infra_error", passed=False))
    sink = ResultSink(tmp_path, resume=True)
    # infra failures are retriable: dropped from file and NOT marked done
    assert sink.n_resumed == 1
    assert not sink.is_done("t2", 0) and not sink.is_done("t3", 0)
    assert len(_read(sink.path)) == 1  # file compacted, no double-count after redo


def test_resume_refuses_mixed_harness_versions(tmp_path):
    old = ResultSink(tmp_path)
    old.record(_outcome("t1", 0, version="aaaa11112222"))
    sink = ResultSink(tmp_path, resume=True)
    with pytest.raises(ValueError, match="resume refused"):
        sink.check_harness_version("bbbb33334444")
    sink.check_harness_version("aaaa11112222")  # same version is fine


# ---- runner integration: crash mid-suite, then resume ------------------------

class _SimulatedCrash(BaseException):
    """Process-death stand-in (like SIGKILL/KeyboardInterrupt): a BaseException,
    so the runner's infra retry (`except Exception`) must NOT swallow it."""


@dataclass
class _CrashPlan:
    crash_on: set  # {(task_id, repeat)} -> raise _SimulatedCrash
    calls: list


def _fake_run_one(plan: _CrashPlan):
    async def fake(task, cfg, out_dir, repeat, sandbox_kind="docker"):
        if (task.task_id, repeat) in plan.crash_on:
            raise _SimulatedCrash
        plan.calls.append((task.task_id, repeat))
        return _outcome(task.task_id, repeat, version=cfg.version)
    return fake


@pytest.mark.asyncio
async def test_crash_preserves_completed_then_resume_finishes(tmp_path, monkeypatch):
    out = tmp_path / "run"
    ids = ["t01_fix_off_by_one", "t05_fix_regex"]

    # Phase 1: second task's repeat crashes the whole process mid-suite.
    plan = _CrashPlan(crash_on={("t05_fix_regex", 0)}, calls=[])
    monkeypatch.setattr(runner_mod, "run_one", _fake_run_one(plan))
    with pytest.raises(_SimulatedCrash):
        await run_suite(REPO / "tasks", out, repeats=1, concurrency=1,
                        task_ids=ids, sandbox_kind="local")
    # The completed outcome is already on disk despite the crash.
    rows = _read(out / "results.jsonl")
    assert [r["task_id"] for r in rows] == ["t01_fix_off_by_one"]

    # Phase 2: resume. Only the missing pair runs; nothing is re-run.
    plan2 = _CrashPlan(crash_on=set(), calls=[])
    monkeypatch.setattr(runner_mod, "run_one", _fake_run_one(plan2))
    summary = await run_suite(REPO / "tasks", out, repeats=1, concurrency=1,
                              task_ids=ids, sandbox_kind="local", resume=True)
    assert plan2.calls == [("t05_fix_regex", 0)]
    rows = _read(out / "results.jsonl")
    assert sorted(r["task_id"] for r in rows) == sorted(ids)  # complete, no duplicates
    assert summary["pass_rate"] == 1.0 and summary["n_tasks"] == 2


@pytest.mark.asyncio
async def test_resume_with_changed_harness_is_refused(tmp_path, monkeypatch):
    out = tmp_path / "run"
    old = ResultSink(out)
    old.record(_outcome("t01_fix_off_by_one", 0, version="000000000000"))
    plan = _CrashPlan(crash_on=set(), calls=[])
    monkeypatch.setattr(runner_mod, "run_one", _fake_run_one(plan))
    with pytest.raises(ValueError, match="resume refused"):
        await run_suite(REPO / "tasks", out, repeats=1, concurrency=1,
                        task_ids=["t01_fix_off_by_one"], sandbox_kind="local",
                        resume=True)
    assert plan.calls == []  # refused before spending anything
