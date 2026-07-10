import shutil
from pathlib import Path

from harnessforge.config import EVOLVABLE_COMPONENTS, HarnessConfig

REPO_HARNESS = Path(__file__).parents[1] / "harness"


def test_load_and_policy():
    cfg = HarnessConfig.load(REPO_HARNESS)
    assert cfg.policy("limits.max_steps") == 8
    assert cfg.policy("nonexistent.key", "fallback") == "fallback"
    assert len(cfg.version) == 12
    assert {t["name"] for t in cfg.tool_descriptions["tools"]} >= {"bash", "finish"}


def test_version_changes_on_edit(tmp_path):
    for name in EVOLVABLE_COMPONENTS:
        shutil.copy(REPO_HARNESS / name, tmp_path / name)
    v1 = HarnessConfig.load(tmp_path).version
    p = tmp_path / "system_prompt.md"
    p.write_text(p.read_text() + "\n- extra rule\n", encoding="utf-8")
    v2 = HarnessConfig.load(tmp_path).version
    assert v1 != v2
