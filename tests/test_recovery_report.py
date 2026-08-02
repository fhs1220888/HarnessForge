from harnessforge.eval.recovery_report import recovery_report
from harnessforge.trace import EventType, TraceWriter


def test_recovery_report_aggregates_checkpoint_and_fork_evidence(tmp_path):
    run = tmp_path / "run"
    trace = TraceWriter(run / "traces", task_id="task", run_id="task-r0")
    trace.emit(EventType.CHECKPOINT, {
        "duration_s": 0.010,
        "snapshot_bytes": 100,
    })
    trace.emit(EventType.CHECKPOINT, {
        "duration_s": 0.030,
        "snapshot_bytes": 300,
    })
    trace.emit(EventType.FAULT_INJECTED, {"after_checkpoint": 1})
    trace.emit(EventType.RESUME, {
        "next_step": 1,
        "tokens_in": 80,
        "tokens_out": 20,
        "cost_usd": 0.004,
    })
    trace.emit(EventType.FORK, {
        "prefix_tokens_in": 120,
        "prefix_tokens_out": 30,
        "prefix_cost_usd": 0.0123,
    })

    report = recovery_report([run])

    assert report["n_traces"] == 1
    assert report["n_checkpoints"] == 2
    assert report["n_resumes"] == 1
    assert report["n_forks"] == 1
    assert report["n_injected_crashes"] == 1
    assert report["checkpoint_latency_ms"]["p50"] == 10.0
    assert report["checkpoint_latency_ms"]["p95"] == 30.0
    assert report["snapshot_bytes"]["max"] == 300
    assert report["fork_prefix_reuse"] == {"tokens": 150, "cost_usd": 0.0123}
    assert report["resume_prefix_reuse"] == {"tokens": 100, "cost_usd": 0.004}


def test_recovery_report_handles_empty_run(tmp_path):
    report = recovery_report([tmp_path])
    assert report["n_traces"] == 0
    assert report["checkpoint_latency_ms"]["p95"] == 0.0
