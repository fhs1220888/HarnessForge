"""Tests for the malformed-structured-output repair loop (selfharness/structured.py)."""

import pytest
from pydantic import BaseModel

from harnessforge.selfharness.structured import (
    REPAIR_PROMPT,
    complete_json_array,
    extract_json_array,
)


class FakeLLM:
    """Returns scripted texts; records every messages list it was called with."""

    def __init__(self, texts: list[str]):
        self.texts = list(texts)
        self.calls: list[list[dict]] = []

    async def complete(self, system, messages, tools=None, max_tokens=4096):
        self.calls.append([dict(m) for m in messages])

        class R:
            text = self.texts.pop(0)

        return R()


class Item(BaseModel):
    name: str
    count: int


GOOD = 'Here you go: [{"name": "a", "count": 1}, {"name": "b", "count": 2}]'
BAD_JSON = '[{"name": "a", "count": 1},]  trailing comma'
NO_ARRAY = "Sorry, I cannot help with that."
BAD_ITEM = '[{"name": "a", "count": 1}, {"name": "b"}]'  # second item missing 'count'


# ---- extract_json_array -----------------------------------------------------

def test_extract_parses_array_embedded_in_prose():
    assert extract_json_array(GOOD) == [{"name": "a", "count": 1}, {"name": "b", "count": 2}]


def test_extract_errors_are_precise():
    with pytest.raises(ValueError, match="no JSON array found"):
        extract_json_array(NO_ARRAY)
    with pytest.raises(ValueError, match="does not parse"):
        extract_json_array(BAD_JSON)


# ---- happy path: no repair needed ------------------------------------------

@pytest.mark.asyncio
async def test_good_output_costs_one_call():
    llm = FakeLLM([GOOD])
    res = await complete_json_array(llm, system="s", prompt="p")
    assert res.ok and res.llm_calls == 1 and not res.repaired and res.errors == []
    assert len(res.items) == 2


# ---- array-level repair -----------------------------------------------------

@pytest.mark.asyncio
async def test_malformed_then_repaired():
    llm = FakeLLM([BAD_JSON, GOOD])
    res = await complete_json_array(llm, system="s", prompt="p")
    assert res.ok and res.llm_calls == 2 and res.repaired
    assert len(res.errors) == 1 and "does not parse" in res.errors[0]
    # The repair turn carried the model's own bad output + the exact error.
    repair_msgs = llm.calls[1]
    assert repair_msgs[1]["role"] == "assistant" and repair_msgs[1]["content"] == BAD_JSON
    assert "could not be used" in repair_msgs[2]["content"]
    assert "does not parse" in repair_msgs[2]["content"]


@pytest.mark.asyncio
async def test_malformed_twice_gives_up_bounded():
    llm = FakeLLM([NO_ARRAY, BAD_JSON, "should never be requested"])
    res = await complete_json_array(llm, system="s", prompt="p", repair_attempts=1)
    assert not res.ok and res.llm_calls == 2 and not res.repaired
    assert len(res.errors) == 2


@pytest.mark.asyncio
async def test_zero_repair_attempts_means_single_shot():
    llm = FakeLLM([BAD_JSON])
    res = await complete_json_array(llm, system="s", prompt="p", repair_attempts=0)
    assert not res.ok and res.llm_calls == 1


# ---- item-level repair ------------------------------------------------------

@pytest.mark.asyncio
async def test_invalid_item_triggers_repair_with_item_error():
    llm = FakeLLM([BAD_ITEM, GOOD])
    res = await complete_json_array(llm, system="s", prompt="p",
                                    item_parser=lambda d: Item(**d))
    assert res.ok and res.repaired and res.llm_calls == 2
    assert all(isinstance(i, Item) for i in res.items) and len(res.items) == 2
    assert "item 1" in llm.calls[1][2]["content"]  # error names the bad item


@pytest.mark.asyncio
async def test_final_attempt_salvages_valid_items():
    llm = FakeLLM([BAD_ITEM, BAD_ITEM])
    res = await complete_json_array(llm, system="s", prompt="p",
                                    item_parser=lambda d: Item(**d))
    # Both attempts had one bad item; the good one is salvaged, not discarded.
    assert res.llm_calls == 2
    assert len(res.items) == 1 and res.items[0].name == "a"
    assert any("item 1" in e for e in res.errors)


def test_repair_prompt_demands_array_only():
    # Guard the contract the callers rely on: repaired output must be parseable
    # by the same extractor, so the prompt must forbid prose/fences.
    msg = REPAIR_PROMPT.format(error="x")
    assert "ONLY" in msg and "JSON array" in msg
