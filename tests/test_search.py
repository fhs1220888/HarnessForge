from harnessforge.selfharness.schema import Proposal, ProposalMemory
from harnessforge.selfharness.search import (
    record_losers,
    select_best_per_group,
)


def _prop(pid, group, accepted, delta):
    return Proposal(
        proposal_id=pid, failure_pattern=group, candidate_group=group,
        component="system_prompt.md", diff="", expected_effect="x",
        accepted=accepted, observed_pass_rate_delta=delta,
    )


def test_selects_best_accepted_per_group():
    props = [
        _prop("a1", "g1", True, 0.10),
        _prop("a2", "g1", True, 0.25),   # best in g1
        _prop("a3", "g1", False, None),
        _prop("b1", "g2", True, 0.30),   # best in g2 (only accepted)
        _prop("b2", "g2", False, -0.1),
    ]
    winners, losers = select_best_per_group(props)
    assert {w.proposal_id for w in winners} == {"a2", "b1"}
    assert {loser.proposal_id for loser in losers} == {"a1", "a3", "b2"}


def test_group_with_no_accepted_has_no_winner():
    props = [_prop("x1", "g", False, -0.2), _prop("x2", "g", False, 0.0)]
    winners, losers = select_best_per_group(props)
    assert winners == []
    assert len(losers) == 2


def test_record_losers_builds_memory():
    mem = ProposalMemory()
    losers = [
        _prop("a1", "g1", False, -0.1),   # regressed
        _prop("a2", "g1", True, 0.05),    # also-ran (accepted but not best)
    ]
    record_losers(mem, losers)
    assert len(mem.rejected) == 2
    note = mem.avoid_note("g1")
    assert "Do NOT repeat" in note
    # a pattern with no history returns the empty sentinel
    assert mem.avoid_note("other") == "None yet."


def test_memory_reason_distinguishes_regression_from_noise():
    mem = ProposalMemory()
    record_losers(mem, [_prop("r", "g", False, -0.2)])
    record_losers(mem, [_prop("n", "g", False, None)])
    reasons = " ".join(r.reason for r in mem.rejected)
    assert "regressed" in reasons
    assert "noise" in reasons
