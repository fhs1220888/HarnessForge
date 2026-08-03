from harnessforge.agent.context import (
    LEDGER_END,
    LEDGER_START,
    compact_messages,
    compact_tool_turns,
    estimate_tokens,
)


def _tool_result(i: int, size: int = 2000) -> dict:
    return {"type": "tool_result", "tool_use_id": f"tu_{i}", "content": f"output {i} " + "x" * size}


def _messages(n_results: int) -> list[dict]:
    msgs = [{"role": "user", "content": "task prompt"}]
    for i in range(n_results):
        msgs.append({"role": "assistant", "content": [
            {"type": "tool_use", "id": f"tu_{i}", "name": "bash", "input": {"command": "ls"}}]})
        msgs.append({"role": "user", "content": [_tool_result(i)]})
    return msgs


def test_keeps_last_n_verbatim():
    msgs, before, after = compact_messages(_messages(10), keep_last_n=3)
    assert after < before
    results = [b for m in msgs if isinstance(m["content"], list)
               for b in m["content"] if b.get("type") == "tool_result"]
    compacted = [r for r in results if str(r["content"]).startswith("[compacted")]
    verbatim = [r for r in results if not str(r["content"]).startswith("[compacted")]
    assert len(compacted) == 7 and len(verbatim) == 3
    # newest results are the verbatim ones
    assert {r["tool_use_id"] for r in verbatim} == {"tu_7", "tu_8", "tu_9"}


def test_noop_when_few_results():
    original = _messages(2)
    msgs, before, after = compact_messages(original, keep_last_n=5)
    assert msgs is original and before == after


def test_original_not_mutated():
    original = _messages(10)
    snapshot = str(original)
    compact_messages(original, keep_last_n=1)
    assert str(original) == snapshot


def test_estimate_tokens_positive():
    assert estimate_tokens(_messages(3)) > 0


def test_short_results_never_grow():
    """Regression: the stub carries a ~200-char head + framing, so 'compacting'
    a short tool result used to make the context BIGGER. Short results must be
    left alone; compaction may never increase token count."""
    msgs = [{"role": "user", "content": "task"}]
    for i in range(6):
        msgs.append({"role": "user", "content": [_tool_result(i, size=50)]})  # all short
    out, before, after = compact_messages(msgs, keep_last_n=1)
    assert after <= before
    results = [b for m in out if isinstance(m["content"], list)
               for b in m["content"] if b.get("type") == "tool_result"]
    assert all(not str(r["content"]).startswith("[compacted") for r in results)


def test_budget_compaction_drops_complete_old_tool_turns():
    original = _messages(10)
    snapshot = str(original)

    out, before, after, dropped = compact_tool_turns(original, keep_last_n=3)

    assert dropped == 7
    assert after < before
    assert str(original) == snapshot
    assert LEDGER_START in out[0]["content"] and LEDGER_END in out[0]["content"]
    assert "bash" in out[0]["content"] and "output 6" in out[0]["content"]
    calls = [
        block
        for message in out
        if message["role"] == "assistant" and isinstance(message["content"], list)
        for block in message["content"]
        if block.get("type") == "tool_use"
    ]
    results = [
        block
        for message in out
        if message["role"] == "user" and isinstance(message["content"], list)
        for block in message["content"]
        if block.get("type") == "tool_result"
    ]
    assert {block["id"] for block in calls} == {block["tool_use_id"] for block in results}
    assert len(calls) == len(results) == 3


def test_budget_compaction_merges_and_bounds_existing_ledger():
    first, _, _, _ = compact_tool_turns(
        _messages(8), keep_last_n=2, ledger_max_chars=500
    )
    # Add enough new complete turns to force a second compaction pass.
    for i in range(8, 14):
        first.append({"role": "assistant", "content": [
            {"type": "tool_use", "id": f"tu_{i}", "name": "bash",
             "input": {"command": f"command-{i}"}}
        ]})
        first.append({"role": "user", "content": [_tool_result(i)]})

    second, before, after, dropped = compact_tool_turns(
        first, keep_last_n=2, ledger_max_chars=500
    )

    assert dropped > 0 and after < before
    ledger = second[0]["content"].split(LEDGER_START, 1)[1].split(LEDGER_END, 1)[0]
    assert len(ledger) <= 550
    assert "command-11" in ledger
    assert "older compacted turns omitted" in ledger


def test_budget_compaction_noop_with_too_few_turns():
    original = _messages(2)
    out, before, after, dropped = compact_tool_turns(original, keep_last_n=3)
    assert out is original and before == after and dropped == 0
