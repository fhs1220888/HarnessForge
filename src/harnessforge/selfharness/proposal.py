"""Proposal generation: turn mined failure patterns into small component diffs.

Each proposal is a unified diff against ONE evolvable component, plus a
structured prediction. Constraints enforced here, before validation:
- component must be in EVOLVABLE_COMPONENTS (declarative-only in v1)
- diff must apply cleanly to the current component
- YAML components must still parse after the diff
"""

from __future__ import annotations

import subprocess
import tempfile
import uuid
from pathlib import Path

import yaml

from ..config import EVOLVABLE_COMPONENTS, HARNESS_DIR
from .schema import MiningReport, Proposal, ProposalMemory

PROPOSAL_PROMPT = """\
You are improving a coding-agent harness. Its evolvable components are:
{components}

Current content of each component is given below. A mined failure pattern:
  id: {pattern_id}
  description: {description}
  example: {example}

Previously-rejected attempts for this pattern (learn from these, do not repeat):
{avoid}

Propose {n_candidates} DISTINCT candidate changes, each targeting exactly one
component, as JSON objects. Make them genuinely different approaches (e.g. edit a
different component, or attack the pattern from a different angle) — not rewordings:
{{"component": "<filename>", "diff": "<unified diff>",
  "expected_effect": "<what should improve>", "expected_pass_rate_delta": <float 0-0.2>,
  "risk": "<cost/behavior risk>"}}

Rules: smallest diff that plausibly fixes the pattern; do not rewrite whole files;
never remove or raise safety/budget limits; YAML must remain valid. Output a JSON array only.

{component_contents}
"""


def apply_diff_to_text(original: str, diff: str) -> str | None:
    """Apply a unified diff to a string via `patch`. Returns None if it fails."""
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "component"
        target.write_text(original, encoding="utf-8")
        proc = subprocess.run(
            ["patch", str(target)], input=diff, capture_output=True, text=True,
        )
        if proc.returncode != 0:
            return None
        return target.read_text(encoding="utf-8")


def sanity_check(proposal: Proposal, harness_dir: Path = HARNESS_DIR) -> str | None:
    """Return an error string, or None if the proposal is structurally valid."""
    try:
        proposal.check_component()
    except ValueError as e:
        return str(e)
    original = (harness_dir / proposal.component).read_text(encoding="utf-8")
    patched = apply_diff_to_text(original, proposal.diff)
    if patched is None:
        return "diff does not apply cleanly"
    if proposal.component.endswith((".yaml", ".yml")):
        try:
            patched_data = yaml.safe_load(patched)
        except yaml.YAMLError as e:
            return f"patched YAML invalid: {e}"
        # Budget limits are the experiment's fixed constraint — proposals must
        # not "improve" pass rate by simply buying more steps/tokens/cost.
        if proposal.component == "loop_policy.yaml":
            old_limits = (yaml.safe_load(original) or {}).get("limits", {})
            new_limits = (patched_data or {}).get("limits", {})
            for key, old_val in old_limits.items():
                new_val = new_limits.get(key, old_val)
                if isinstance(old_val, (int, float)) and new_val > old_val:
                    return f"budget limit {key} may not be raised ({old_val} -> {new_val})"
    return None


async def generate(report: MiningReport, max_proposals: int = 6,
                   harness_dir: Path = HARNESS_DIR, candidates_per_pattern: int = 3,
                   memory: ProposalMemory | None = None) -> list[Proposal]:
    """Generate multiple distinct candidate diffs per failure pattern.

    Candidates targeting the same pattern share `candidate_group = pattern_id`, so
    the round driver can validate several and keep only the best. Past rejections
    (memory) are injected so the proposer avoids known dead ends.
    """
    import json
    import os

    from ..agent.llm import LLMClient

    contents = "\n\n".join(
        f"=== {name} ===\n{(harness_dir / name).read_text(encoding='utf-8')}"
        for name in EVOLVABLE_COMPONENTS
    )
    llm = LLMClient(model=os.environ.get("MINER_MODEL"))
    proposals: list[Proposal] = []

    for pattern in report.patterns:
        if len(proposals) >= max_proposals:
            break
        avoid = memory.avoid_note(pattern.pattern_id) if memory else "None yet."
        resp = await llm.complete(
            system="You are a careful harness engineer. Minimal, reversible changes only.",
            messages=[{"role": "user", "content": PROPOSAL_PROMPT.format(
                components=", ".join(EVOLVABLE_COMPONENTS),
                pattern_id=pattern.pattern_id,
                description=pattern.description,
                example=pattern.example_excerpt,
                avoid=avoid,
                n_candidates=candidates_per_pattern,
                component_contents=contents,
            )}],
            max_tokens=8192,
        )
        try:
            raw = json.loads(resp.text[resp.text.find("[") : resp.text.rfind("]") + 1])
        except json.JSONDecodeError:
            continue  # TODO: repair prompt
        for item in raw:
            p = Proposal(
                proposal_id=f"prop-{uuid.uuid4().hex[:8]}",
                failure_pattern=pattern.pattern_id,
                candidate_group=pattern.pattern_id,
                **item,
            )
            err = sanity_check(p, harness_dir)
            if err is None:
                proposals.append(p)
            else:
                p.validation_notes = f"rejected pre-validation: {err}"

    return proposals
