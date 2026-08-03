from harnessforge.eval.tb_runner import _aggregate_partial_traces
from harnessforge.trace import EventType, TraceWriter


def test_partial_trace_usage_preserves_infra_cost_ledger(tmp_path):
    first = TraceWriter(tmp_path, task_id="task-r0")
    first.emit(
        EventType.LLM_RESPONSE,
        {"stop_reason": "tool_use"},
        tokens_in=100,
        tokens_out=20,
        cost_usd=0.25,
    )
    second = TraceWriter(tmp_path, task_id="task-r0")
    second.emit(
        EventType.LLM_RESPONSE,
        {"stop_reason": "tool_use"},
        tokens_in=200,
        tokens_out=30,
        cost_usd=0.5,
    )

    calls, tokens, cost = _aggregate_partial_traces({first.path, second.path})

    assert calls == 2
    assert tokens == 350
    assert cost == 0.75
