from __future__ import annotations

import time

import pytest

from harnessforge.agent.tools import ToolExecutor
from harnessforge.sandbox.local_sandbox import LocalSandbox


@pytest.mark.asyncio
async def test_run_maps_only_canonical_workspace_token(tmp_path):
    workspace = tmp_path / "workspace-cache" / "workspaces" / "task"
    async with LocalSandbox(workspace) as sandbox:
        canonical = await sandbox.run("cd /workspace && test -f marker.txt || touch marker.txt")
        already_expanded = await sandbox.run(f"cd {workspace} && test -f marker.txt")

    assert canonical.exit_code == 0
    assert already_expanded.exit_code == 0


@pytest.mark.asyncio
async def test_timeout_reaps_shell_and_child_processes(tmp_path):
    async with LocalSandbox(tmp_path / "task") as sandbox:
        started = time.monotonic()
        result = await sandbox.run("sleep 60 & wait", timeout_s=0.05)

    assert result.exit_code == 124
    assert "timed out after 0.05s" in result.stderr
    # Shared CI runners can be descheduled while the killed process group is
    # being reaped.  Keep this bound far below the leaked child's 60-second
    # lifetime without turning scheduler latency into a flaky correctness test.
    assert time.monotonic() - started < 5


@pytest.mark.asyncio
async def test_file_tool_rejects_sibling_with_shared_path_prefix(tmp_path):
    workspace = tmp_path / "task"
    sibling = tmp_path / "task-secret"
    sibling.write_text("secret", encoding="utf-8")

    async with LocalSandbox(workspace) as sandbox:
        result = await ToolExecutor(sandbox).execute(
            "read_file", {"path": "../task-secret"}
        )

    assert result.error is True
    assert "path escapes workspace" in result.output


@pytest.mark.asyncio
async def test_apply_patch_accepts_plain_file_headers(tmp_path):
    workspace = tmp_path / "task"
    workspace.mkdir()
    target = workspace / "answer.txt"
    target.write_text("old\n", encoding="utf-8")
    patch = """--- answer.txt
+++ answer.txt
@@ -1 +1 @@
-old
+new
"""

    async with LocalSandbox(workspace) as sandbox:
        result = await ToolExecutor(sandbox).execute("apply_patch", {"patch": patch})

    assert result.error is False
    assert result.exit_code == 0
    assert target.read_text(encoding="utf-8") == "new\n"


@pytest.mark.asyncio
async def test_apply_patch_surfaces_failure_instead_of_success_message(tmp_path):
    workspace = tmp_path / "task"
    workspace.mkdir()
    target = workspace / "answer.txt"
    target.write_text("old\n", encoding="utf-8")
    patch = """--- answer.txt
+++ answer.txt
@@ -1 +1 @@
-different
+new
"""

    async with LocalSandbox(workspace) as sandbox:
        result = await ToolExecutor(sandbox).execute("apply_patch", {"patch": patch})

    assert result.error is True
    assert result.exit_code == 1
    assert "does not apply cleanly" in result.output
    assert "Patch applied." not in result.output
    assert target.read_text(encoding="utf-8") == "old\n"
