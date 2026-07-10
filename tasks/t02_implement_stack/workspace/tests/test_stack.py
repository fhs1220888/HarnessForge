import pytest

from stack import Stack


def test_push_pop_order():
    s = Stack()
    s.push(1)
    s.push(2)
    assert s.pop() == 2
    assert s.pop() == 1


def test_peek_does_not_remove():
    s = Stack()
    s.push("x")
    assert s.peek() == "x"
    assert len(s) == 1


def test_empty_behavior():
    s = Stack()
    assert s.is_empty()
    with pytest.raises(IndexError):
        s.pop()
    with pytest.raises(IndexError):
        s.peek()
