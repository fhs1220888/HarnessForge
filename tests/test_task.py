from pathlib import Path

from harnessforge.eval.task import discover_tasks

TASKS_ROOT = Path(__file__).parents[1] / "tasks"


def test_discover_example_task():
    tasks = discover_tasks(TASKS_ROOT)
    ids = [t.task_id for t in tasks]
    assert "t01_fix_off_by_one" in ids
    t01 = next(t for t in tasks if t.task_id == "t01_fix_off_by_one")
    assert "pytest" in t01.check
    assert t01.workspace_dir is not None and (t01.workspace_dir / "calc.py").exists()
