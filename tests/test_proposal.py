import difflib
import shutil
from pathlib import Path

from harnessforge.selfharness.proposal import apply_diff_to_text, sanity_check
from harnessforge.selfharness.schema import Proposal

REPO_HARNESS = Path(__file__).parents[1] / "harness"


def make_diff(old: str, new: str, name: str = "component") -> str:
    return "".join(difflib.unified_diff(
        old.splitlines(keepends=True), new.splitlines(keepends=True),
        fromfile=f"a/{name}", tofile=f"b/{name}",
    ))


def test_apply_diff_roundtrip():
    old = "line1\nline2\nline3\n"
    new = "line1\nline2 CHANGED\nline3\n"
    assert apply_diff_to_text(old, make_diff(old, new)) == new


def test_apply_bad_diff_returns_none():
    assert apply_diff_to_text("completely\ndifferent\n",
                              make_diff("aaa\nbbb\n", "aaa\nccc\n")) is None


def _proposal(component: str, diff: str) -> Proposal:
    return Proposal(proposal_id="p1", failure_pattern="x", component=component,
                    diff=diff, expected_effect="test")


def test_sanity_check_accepts_valid_yaml_edit(tmp_path):
    for f in REPO_HARNESS.glob("*"):
        if f.is_file():
            shutil.copy(f, tmp_path / f.name)
    old = (tmp_path / "loop_policy.yaml").read_text(encoding="utf-8")
    new = old.replace("keep_last_n_tool_results: 5", "keep_last_n_tool_results: 4")
    assert sanity_check(_proposal("loop_policy.yaml", make_diff(old, new)), tmp_path) is None


def test_sanity_check_rejects_non_evolvable_component(tmp_path):
    err = sanity_check(_proposal("agent/loop.py", "whatever"), tmp_path)
    assert err is not None and "not evolvable" in err


def test_sanity_check_rejects_raised_budget_limits(tmp_path):
    for f in REPO_HARNESS.glob("*"):
        if f.is_file():
            shutil.copy(f, tmp_path / f.name)
    old = (tmp_path / "loop_policy.yaml").read_text(encoding="utf-8")
    new = old.replace("max_steps: 8", "max_steps: 50")
    err = sanity_check(_proposal("loop_policy.yaml", make_diff(old, new)), tmp_path)
    assert err is not None and "may not be raised" in err


def test_sanity_check_allows_lowered_budget_limits(tmp_path):
    for f in REPO_HARNESS.glob("*"):
        if f.is_file():
            shutil.copy(f, tmp_path / f.name)
    old = (tmp_path / "loop_policy.yaml").read_text(encoding="utf-8")
    new = old.replace("max_steps: 8", "max_steps: 6")
    assert sanity_check(_proposal("loop_policy.yaml", make_diff(old, new)), tmp_path) is None


def test_sanity_check_rejects_invalid_yaml(tmp_path):
    for f in REPO_HARNESS.glob("*"):
        if f.is_file():
            shutil.copy(f, tmp_path / f.name)
    old = (tmp_path / "loop_policy.yaml").read_text(encoding="utf-8")
    new = old.replace("max_steps: 8", "max_steps: [unclosed")
    err = sanity_check(_proposal("loop_policy.yaml", make_diff(old, new)), tmp_path)
    assert err is not None and "YAML" in err
