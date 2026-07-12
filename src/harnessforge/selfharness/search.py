"""Search over candidate proposals: keep the best per pattern, record the rest
as memory. Pure functions — the round driver wires them to validation.
"""

from __future__ import annotations

from .schema import Proposal, ProposalMemory


def select_best_per_group(validated: list[Proposal]) -> tuple[list[Proposal], list[Proposal]]:
    """Given validated candidates, return (winners, losers).

    A winner is the accepted candidate with the largest observed pass-rate delta
    within its candidate_group; at most one winner per group. Everything else
    (rejected, or accepted-but-not-best) is a loser to be recorded as memory and
    not merged.
    """
    by_group: dict[str, list[Proposal]] = {}
    for p in validated:
        by_group.setdefault(p.candidate_group or p.proposal_id, []).append(p)

    winners: list[Proposal] = []
    losers: list[Proposal] = []
    for _group, cands in by_group.items():
        accepted = [c for c in cands if c.accepted
                    and c.observed_pass_rate_delta is not None]
        if not accepted:
            losers.extend(cands)
            continue
        best = max(accepted, key=lambda c: c.observed_pass_rate_delta)
        winners.append(best)
        losers.extend(c for c in cands if c is not best)
    return winners, losers


def record_losers(memory: ProposalMemory, losers: list[Proposal]) -> ProposalMemory:
    """Fold rejected/also-ran candidates into memory for future rounds."""
    for p in losers:
        if p.accepted is False or p.observed_pass_rate_delta is not None:
            reason = _reason_for(p)
            memory.add(p, reason)
    return memory


def _reason_for(p: Proposal) -> str:
    if p.accepted is False:
        d = p.observed_pass_rate_delta
        if d is not None and d <= 0:
            return "no effect or regressed under paired validation"
        return "did not clear the effect-size threshold (likely noise)"
    return "accepted but a sibling candidate scored higher"
