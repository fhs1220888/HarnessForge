"""Local (non-Docker) sandbox: runs commands directly in the workspace directory.

Same interface as docker_sandbox.Sandbox. NOT isolated — use only for unit tests,
CI without Docker, and trusted smoke runs. The eval runner selects it via
--sandbox local.
"""

from __future__ import annotations

import asyncio
import shlex
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
        command = command.replace("/workspace", str(self.workspace))
        t0 = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            "bash", "-lc", command,
            cwd=self.workspace,
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
        if not str(resolved).startswith(str(self.workspace)):
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
            dry = await self.run(f"patch -p1 --dry-run < {shlex.quote(patch_file.name)}")
            if dry.exit_code != 0:
                return ExecResult("", f"patch does not apply cleanly:\n{dry.stdout}{dry.stderr}",
                                  1, dry.duration_s)
            return await self.run(f"patch -p1 < {shlex.quote(patch_file.name)}")
        finally:
            patch_file.unlink(missing_ok=True)

    async def __aenter__(self) -> "LocalSandbox":
        await self.start()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.stop()
