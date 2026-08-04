from __future__ import annotations

import json

from harnessforge.selfharness.usage import campaign_usage


def test_campaign_usage_combines_agent_traces_and_meta_ledgers(tmp_path):
    traces = tmp_path / "round1" / "validation" / "traces"
    traces.mkdir(parents=True)
    events = [
        {
            "event_type": "llm_response",
            "tokens_in": 120,
            "tokens_out": 30,
            "cost_usd": 0.003,
        },
        {"event_type": "tool_call", "tokens_in": 999, "cost_usd": 9.0},
        {
            "event_type": "llm_response",
            "tokens_in": 80,
            "tokens_out": 20,
            "cost_usd": 0.002,
        },
    ]
    (traces / "task-r0.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "round1/meta_usage.json").write_text(
        json.dumps({
            "schema_version": 1,
            "total": {
                "model_calls": 2,
                "tokens_in": 500,
                "tokens_out": 100,
                "cost_usd": 0.02,
            },
        }),
        encoding="utf-8",
    )

    usage = campaign_usage(tmp_path)

    assert usage["agent"] == {
        "model_calls": 2,
        "tokens_in": 200,
        "tokens_out": 50,
        "total_tokens": 250,
        "cost_usd": 0.005,
    }
    assert usage["meta"]["cost_usd"] == 0.02
    assert usage["total"] == {
        "model_calls": 4,
        "tokens_in": 700,
        "tokens_out": 150,
        "total_tokens": 850,
        "cost_usd": 0.025,
    }
