from harnessforge.agent.context import compact_messages, estimate_tokens


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
