"""Sandbox for Terminal-Bench tasks.

Differs from the native Docker sandbox:
- boots the task's *prebuilt* image (files already baked in at /app), no mount
- network enabled (TB tasks routinely fetch models/data)
- verification copies the task's tests/ into the container, runs test.sh, and
  reads /logs/verifier/reward.txt

Reuses ExecResult and the _host/run helpers by subclassing Sandbox.
"""

from __future__ import annotations

from pathlib import Path

from .docker_sandbox import ExecResult, Sandbox


class TBSandbox(Sandbox):
    def __init__(self, image: str, test_dir: Path, memory_mb: int = 2048,
                 allow_internet: bool = True):
        # workspace is unused for TB (files are baked into the image); pass /tmp
        super().__init__(workspace=Path("/tmp"), image=image)
        self.test_dir = Path(test_dir)
        self.memory_mb = memory_mb
        self.allow_internet = allow_internet

    # Large ML images (mteb, pytorch, …) can be several GB and take many minutes
    # to pull. Pulling is separated from `docker run` and given a generous timeout;
    # once the image is local, `docker run` is fast. Pre-pull with pull_images()
    # to keep image download out of the timed eval entirely.
    PULL_TIMEOUT_S = 1200

    async def _ensure_image(self) -> None:
        inspect = await self._host("docker", "image", "inspect", self.image, timeout_s=30)
        if inspect.exit_code == 0:
            return  # already local
        pull = await self._host("docker", "pull", self.image, timeout_s=self.PULL_TIMEOUT_S)
        if pull.exit_code != 0:
            raise RuntimeError(f"docker pull failed ({self.image}): {pull.stderr[-300:]}")

    async def start(self) -> None:
        await self._ensure_image()
        argv = [
            "docker", "run", "-d", "--rm",
            "--name", self.container,
            "--memory", f"{self.memory_mb}m", "--cpus", "1",
            "-w", "/app",
        ]
        if not self.allow_internet:
            argv += ["--network", "none"]
        argv += [self.image, "sleep", "infinity"]
        res = await self._host(*argv, timeout_s=120)
        if res.exit_code != 0:
            raise RuntimeError(f"TB sandbox start failed ({self.image}): {res.stderr}")
        self._started = True
        # TB's test.sh writes to /logs/verifier/reward.txt.
        await self.run("mkdir -p /logs/verifier")

    async def run_reward_check(self, reward_command: str, timeout_s: float) -> bool:
        """Copy tests/ into the container, run the reward check, return pass/fail."""
        copy = await self._host("docker", "cp", f"{self.test_dir}/.",
                                f"{self.container}:/tests", timeout_s=120)
        if copy.exit_code != 0:
            raise RuntimeError(f"failed to copy tests into container: {copy.stderr}")
        res: ExecResult = await self.run(reward_command, timeout_s=timeout_s)
        return res.exit_code == 0
