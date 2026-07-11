"""Adapter parsing tests using a synthetic TB-format task fixture.

Real TB tasks need Docker + large prebuilt images, so we don't run them here;
we verify the adapter parses task.toml/instruction.md and builds the reward
check exactly as TB's conventions require.
"""

import textwrap

import pytest

from harnessforge.eval.tb_adapter import TBTask, discover_tb_tasks, load_subset


def make_tb_task(root, name="demo-task", docker_image="example/demo:1"):
    d = root / name
    (d / "tests").mkdir(parents=True)
    (d / "instruction.md").write_text("Do the thing in /app.\n", encoding="utf-8")
    (d / "tests" / "test.sh").write_text("#!/bin/bash\necho 1 > /logs/verifier/reward.txt\n")
    (d / "task.toml").write_text(textwrap.dedent(f"""\
        schema_version = "1.1"
        [task]
        name = "terminal-bench/{name}"
        [metadata]
        difficulty = "medium"
        category = "software-engineering"
        expert_time_estimate_min = 20.0
        [verifier]
        timeout_sec = 900.0
        [environment]
        docker_image = "{docker_image}"
        memory_mb = 2048
        allow_internet = true
    """), encoding="utf-8")
    return d


def test_parse_tb_task(tmp_path):
    make_tb_task(tmp_path)
    task = TBTask.load(tmp_path / "demo-task")
    assert task.task_id == "demo-task"
    assert task.docker_image == "example/demo:1"
    assert task.difficulty == "medium"
    assert task.verifier_timeout_s == 900.0
    assert task.allow_internet is True
    assert "Do the thing" in task.instruction


def test_reward_check_command_reads_reward_file(tmp_path):
    make_tb_task(tmp_path)
    task = TBTask.load(tmp_path / "demo-task")
    cmd = task.reward_check_command()
    assert "/tests/test.sh" in cmd
    assert "/logs/verifier/reward.txt" in cmd
    assert '= "1"' in cmd


def test_discover_multiple(tmp_path):
    make_tb_task(tmp_path, name="a")
    make_tb_task(tmp_path, name="b")
    tasks = discover_tb_tasks(tmp_path)
    assert {t.task_id for t in tasks} == {"a", "b"}


def test_load_subset_errors_on_missing(tmp_path):
    make_tb_task(tmp_path, name="a")
    with pytest.raises(FileNotFoundError) as e:
        load_subset(tmp_path, subset=["a", "does-not-exist"])
    assert "does-not-exist" in str(e.value)


def test_load_subset_exact(tmp_path):
    make_tb_task(tmp_path, name="a")
    make_tb_task(tmp_path, name="b")
    tasks = load_subset(tmp_path, subset=["b", "a"])
    assert [t.task_id for t in tasks] == ["b", "a"]  # order follows the subset list
