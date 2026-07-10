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


class MiningReport(BaseModel):
    run_dir: str
    harness_version: str
    n_failed_runs: int
    patterns: list[FailurePattern] = Field(default_factory=list)
