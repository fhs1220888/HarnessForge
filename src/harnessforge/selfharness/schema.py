"""Shared data structures for the self-harness loop.

The proposal carries a structured *prediction*; after validation the observed
effect is backfilled. Accumulated proposals form the calibration table
(predicted vs. actual improvement) — the project's key differentiator.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..config import EVOLVABLE_COMPONENTS


class FailurePattern(BaseModel):
    pattern_id: str                      # e.g. "ignores-test-traceback"
    description: str                     # human-readable failure mode
    evidence_runs: list[str]             # run_ids exhibiting this pattern
    frequency: int                       # how many failed runs match
    example_excerpt: str = ""            # short trace excerpt as evidence


class Proposal(BaseModel):
    proposal_id: str
    failure_pattern: str                 # pattern_id this targets
    component: str                       # must be in EVOLVABLE_COMPONENTS
    diff: str                            # unified diff against the component file
    expected_effect: str                 # prediction, e.g. "recover from failing tests"
    expected_pass_rate_delta: float = 0.0  # predicted delta on the validation set
    risk: str = ""                       # e.g. "slightly more tokens per task"

    # Search bookkeeping: candidates that target the same pattern share a group,
    # so the round driver can validate several and keep only the best.
    candidate_group: str = ""

    # Backfilled by the validation gate:
    observed_pass_rate_delta: float | None = None
    observed_cost_delta_pct: float | None = None
    accepted: bool | None = None
    validation_notes: str = ""

    def check_component(self) -> None:
        if self.component not in EVOLVABLE_COMPONENTS:
            raise ValueError(
                f"component {self.component!r} is not evolvable in v1 "
                f"(allowed: {EVOLVABLE_COMPONENTS})"
            )


class RejectedAttempt(BaseModel):
    """One past proposal that did not survive validation, kept as memory so the
    proposer doesn't re-suggest the same dead end in later rounds."""
    failure_pattern: str
    component: str
    change_summary: str                  # short human description of what was tried
    reason: str                          # why it was rejected (noise / regressed / no effect)
    observed_pass_rate_delta: float | None = None


class ProposalMemory(BaseModel):
    """Accumulated rejections across rounds, injected into the proposal prompt."""
    rejected: list[RejectedAttempt] = Field(default_factory=list)

    def add(self, proposal: "Proposal", reason: str) -> None:
        self.rejected.append(RejectedAttempt(
            failure_pattern=proposal.failure_pattern,
            component=proposal.component,
            change_summary=proposal.expected_effect[:160],
            reason=reason,
            observed_pass_rate_delta=proposal.observed_pass_rate_delta,
        ))

    def avoid_note(self, pattern_id: str, max_items: int = 6) -> str:
        """Prompt snippet listing dead ends for this pattern (and general ones)."""
        relevant = [r for r in self.rejected if r.failure_pattern == pattern_id][:max_items]
        if not relevant:
            return "None yet."
        return "\n".join(
            f"- tried editing {r.component} to \"{r.change_summary}\" -> rejected "
            f"({r.reason}"
            + (f", observed Δ {r.observed_pass_rate_delta:+.2f}"
               if r.observed_pass_rate_delta is not None else "")
            + "). Do NOT repeat this."
            for r in relevant
        )


class MiningReport(BaseModel):
    run_dir: str
    harness_version: str
    n_failed_runs: int
    patterns: list[FailurePattern] = Field(default_factory=list)
