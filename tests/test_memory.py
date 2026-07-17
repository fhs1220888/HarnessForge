"""Unit tests for episode-scoped TaskMemory (agent/memory.py)."""

from harnessforge.agent.memory import HEADER, TaskMemory


def test_write_and_render():
    m = TaskMemory()
    msg = m.write("root_cause", "off-by-one in sum_range")
    assert "saved" in msg and "1/20" in msg
    r = m.render()
    assert HEADER in r
    assert "- root_cause: off-by-one in sum_range" in r


def test_render_empty_is_empty_string():
    assert TaskMemory().render() == ""


def test_overwrite_same_key_updates_not_duplicates():
    m = TaskMemory()
    m.write("plan", "step 1")
    msg = m.write("plan", "step 2")
    assert "updated" in msg
    assert len(m) == 1
    assert "step 2" in m.render() and "step 1" not in m.render()


def test_fifo_eviction_beyond_max_notes():
    m = TaskMemory(max_notes=2)
    m.write("a", "1")
    m.write("b", "2")
    msg = m.write("c", "3")
    assert "evicted oldest note 'a'" in msg
    assert len(m) == 2
    assert "- a:" not in m.render()
    assert "- b: 2" in m.render() and "- c: 3" in m.render()


def test_overwrite_does_not_evict():
    m = TaskMemory(max_notes=2)
    m.write("a", "1")
    m.write("b", "2")
    m.write("a", "1-updated")
    assert len(m) == 2
    assert "- b: 2" in m.render()


def test_content_truncated_at_max_chars():
    m = TaskMemory(max_chars_per_note=10)
    msg = m.write("k", "x" * 50)
    assert "truncated to 10 chars" in msg
    assert "- k: " + "x" * 10 in m.render()
    assert "x" * 11 not in m.render()


def test_bounds_floor_at_one():
    m = TaskMemory(max_notes=0, max_chars_per_note=0)
    m.write("k", "abc")
    assert len(m) == 1
    assert "- k: a" in m.render()
