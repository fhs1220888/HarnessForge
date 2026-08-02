"""Local (non-Docker) sandbox: runs commands directly in the workspace directory.

Same interface as docker_sandbox.Sandbox. NOT isolated — use only for unit tests,
CI without Docker, and trusted smoke runs. The eval runner selects it via
--sandbox local.
"""

from __future__ import annotations

import asyncio
import os
import re
import shlex
import sys
import time
from pathlib import Path

from .docker_sandbox import ExecResult


class LocalSandbox:
    def __init__(self, workspace: Path):
        self.workspace = Path(workspace).resolve()

    async def start(self) -> None:
        self.workspace.mkdir(parents=True, exist_ok=True)

    async def stop(self) -> None:
        pass

    async def run(self, command: str, timeout_s: float = 60) -> ExecResult:
        # Task checks and prompts are written against the Docker layout where the
        # workspace is mounted at /workspace. Map that path onto the local dir.
        # Match a shell path token, not the same substring inside an already
        # expanded host path such as ".../workspaces/...".
        command = re.sub(
            r"(?<![\w./-])/workspace(?=$|[^\w.-])",
            lambda _match: str(self.workspace),
            command,
        )
        t0 = time.monotonic()
        # A direct invocation such as `.venv/bin/pytest` does not activate that
        # virtualenv for child processes. Put the interpreter that is running
        # HarnessForge first on PATH so task commands using the conventional
        # `python` name resolve consistently on macOS, Linux, and CI.
        env = os.environ.copy()
        # Do not resolve the executable symlink: in a virtualenv it intentionally
        # points at the base interpreter while its *unresolved* parent contains
        # the environment's installed console scripts and site configuration.
        python_bin = str(Path(sys.executable).parent)
        env["PATH"] = python_bin + os.pathsep + env.get("PATH", "")
        proc = await asyncio.create_subprocess_exec(
            "bash", "-c", command,
            cwd=self.workspace,
            env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
        except asyncio.TimeoutError:
            proc.kill()
            return ExecResult("", f"timed out after {timeout_s}s", 124, time.monotonic() - t0)
        return ExecResult(
            out.decode(errors="replace"), err.decode(errors="replace"),
            proc.returncode or 0, time.monotonic() - t0,
        )

    def _resolve(self, path: str) -> Path:
        """Map absolute /workspace/... paths and relative paths into the workspace."""
        p = Path(path)
        if p.is_absolute():
            try:
                p = p.relative_to("/workspace")
            except ValueError:
                raise PermissionError(f"path outside workspace: {path}")
        resolved = (self.workspace / p).resolve()
        if not resolved.is_relative_to(self.workspace):
            raise PermissionError(f"path escapes workspace: {path}")
        return resolved

    async def read_file(self, path: str) -> str:
        return self._resolve(path).read_text(encoding="utf-8")

    async def write_file(self, path: str, content: str) -> None:
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    async def apply_patch(self, patch: str) -> ExecResult:
        patch_file = self.workspace / "_hforge.patch"
        patch_file.write_text(patch, encoding="utf-8")
        try:
            failures = []
            duration_s = 0.0
            # Models commonly emit either git-style a/file headers (-p1) or
            # plain file headers (-p0). Accept both while retaining the
            # all-hunks dry-run gate.
            for strip in (1, 0):
                dry = await self.run(
                    f"patch -p{strip} --dry-run < {shlex.quote(patch_file.name)}"
                )
                duration_s += dry.duration_s
                if dry.exit_code == 0:
                    applied = await self.run(
                        f"patch -p{strip} < {shlex.quote(patch_file.name)}"
                    )
                    applied.duration_s += duration_s
                    return applied
                failures.append(f"-p{strip}:\n{dry.stdout}{dry.stderr}")
            return ExecResult(
                "",
                "patch does not apply cleanly:\n" + "\n".join(failures),
                1,
                duration_s,
            )
        finally:
            patch_file.unlink(missing_ok=True)

    async def __aenter__(self) -> "LocalSandbox":
        await self.start()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.stop()
