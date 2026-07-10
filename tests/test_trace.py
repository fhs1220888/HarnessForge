from harnessforge.trace import EventType, TraceWriter, load_trace


def test_trace_roundtrip(tmp_path):
    w = TraceWriter(tmp_path, task_id="t01")
    w.emit(EventType.RUN_START, {"model": "test"})
    w.emit(EventType.LLM_RESPONSE, {"text": "hi"}, tokens_in=100, tokens_out=50, cost_usd=0.001)
    w.emit(EventType.TERMINATION, {"exit_reason": "finished_done"})

    events = load_trace(w.path)
    assert len(events) == 3
    assert events[0]["event_type"] == "run_start"
    assert events[1]["tokens_in"] == 100
    assert [e["step"] for e in events] == [0, 1, 2]
    assert w.total_tokens_in == 100
    assert w.total_cost_usd == 0.001
