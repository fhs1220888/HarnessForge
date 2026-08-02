"""Docker-based sandbox: one container per task, workspace mounted at /workspace.

v1 skeleton uses `docker exec` via asyncio subprocess. Sufficient for
terminal-bench-style tasks; swap for a proper API (docker SDK) later if needed.
"""

from __future__ import annotations

import asyncio
import shlex
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

DEFAULT_IMAGE = "python:3.12-slim"


@dataclass
class ExecResult:
    stdout: str
    stderr: str
    exit_code: int
    duration_s: float


class Sandbox:
    def __init__(self, workspace: Path, image: str = DEFAULT_IMAGE):
        self.workspace = Path(workspace).resolve()
        self.image = image
        self.container = f"hforge-{uuid.uuid4().hex[:10]}"
        self._started = False

    async def _host(self, *argv: str, timeout_s: float = 120) -> ExecResult:
        t0 = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
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

    async def start(self) -> None:
        res = await self._host(
            "docker", "run", "-d", "--rm",
            "--name", self.container,
            "--network", "none",            # no network for the agent under test
            "--memory", "1g", "--cpus", "1",
            "-v", f"{self.workspace}:/workspace",
            "-w", "/workspace",
            self.image, "sleep", "infinity",
        )
        if res.exit_code != 0:
            raise RuntimeError(f"sandbox start failed: {res.stderr}")
        self._started = True

    async def stop(self) -> None:
        if self._started:
            await self._host("docker", "kill", self.container)
            self._started = False

    async def run(self, command: str, timeout_s: float = 60) -> ExecResult:
        return await self._host(
            "docker", "exec", self.container, "bash", "-lc", command,
            timeout_s=timeout_s,
        )

    async def read_file(self, path: str) -> str:
        res = await self.run(f"cat {shlex.quote(path)}")
        if res.exit_code != 0:
            raise FileNotFoundError(res.stderr.strip() or path)
        return res.stdout

    async def write_file(self, path: str, content: str) -> None:
        # Write via stdin to avoid quoting issues with large content.
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", "-i", self.container, "bash", "-lc",
            f"mkdir -p $(dirname {shlex.quote(path)}) && cat > {shlex.quote(path)}",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate(content.encode())
        if proc.returncode != 0:
            raise RuntimeError(f"write failed: {err.decode(errors='replace')}")

    async def apply_patch(self, patch: str) -> ExecResult:
        """Dry-run every hunk, accepting git-style or plain diff paths."""
        await self.write_file("/tmp/_hforge.patch", patch)
        failures = []
        duration_s = 0.0
        for strip in (1, 0):
            dry = await self.run(
                f"patch -p{strip} --dry-run -d /workspace < /tmp/_hforge.patch"
            )
            duration_s += dry.duration_s
            if dry.exit_code == 0:
                applied = await self.run(
                    f"patch -p{strip} -d /workspace < /tmp/_hforge.patch"
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

    async def __aenter__(self) -> "Sandbox":
        await self.start()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.stop()
