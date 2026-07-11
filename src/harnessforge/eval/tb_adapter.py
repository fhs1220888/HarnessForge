"""Terminal-Bench 2.0 adapter.

Terminal-Bench (https://github.com/harbor-framework/terminal-bench-2, Apache-2.0)
tasks differ from our native tasks in three ways this adapter bridges:

1. Each task ships a *prebuilt* Docker image (task.toml -> [environment].docker_image)
   with the task files baked in (usually under /app). We do NOT mount a workspace;
   we run the agent inside that image.
2. The prompt is instruction.md, not a yaml field.
3. Verification is not "run pytest and check exit code". It is: copy the task's
   tests/ into the container, run tests/test.sh, which writes a reward (1/0) to
   /logs/verifier/reward.txt. We read that file for ground truth.

Because these tasks are much harder than our native suite (expert time 5-90 min),
the TB runner uses a *separate, larger* step/token budget — see TBRunConfig — so
that "did the harness help" is measurable rather than everything failing at 8 steps.

This module only parses/represents TB tasks and defines how to check them. Actually
running them requires Docker and the TB-specific sandbox path in tb_runner.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import toml


@dataclass
class TBTask:
    task_id: str
    instruction: str            # contents of instruction.md (the agent prompt)
    docker_image: str           # prebuilt image with task files baked in
    test_dir: Path              # local tests/ dir to copy into the container
    difficulty: str
    category: str
    verifier_timeout_s: float
    memory_mb: int
    allow_internet: bool
    task_dir: Path

    # Where TB conventions put things inside the container:
    WORKDIR = "/app"
    TEST_MOUNT = "/tests"
    REWARD_PATH = "/logs/verifier/reward.txt"

    @classmethod
    def load(cls, task_dir: Path) -> "TBTask":
        task_dir = Path(task_dir)
        meta = toml.loads((task_dir / "task.toml").read_text(encoding="utf-8"))
        env = meta.get("environment", {})
        md = meta.get("metadata", {})
        return cls(
            task_id=task_dir.name,
            instruction=(task_dir / "instruction.md").read_text(encoding="utf-8"),
            docker_image=env["docker_image"],
            test_dir=task_dir / "tests",
            difficulty=md.get("difficulty", "?"),
            category=md.get("category", "?"),
            verifier_timeout_s=meta.get("verifier", {}).get("timeout_sec", 600.0),
            memory_mb=env.get("memory_mb", 2048),
            allow_internet=env.get("allow_internet", False),
            task_dir=task_dir,
        )

    def reward_check_command(self) -> str:
        """Shell run *inside the container* after the agent finishes.
        TB's test.sh writes reward.txt; we surface its content as the exit code.
        """
        return (
            f"bash {self.TEST_MOUNT}/test.sh >/dev/null 2>&1; "
            f"test \"$(cat {self.REWARD_PATH} 2>/dev/null)\" = \"1\""
        )


def discover_tb_tasks(tb_root: Path) -> list[TBTask]:
    return [
        TBTask.load(d)
        for d in sorted(Path(tb_root).iterdir())
        if (d / "task.toml").exists()
    ]


# --- tb-subset-v1 ------------------------------------------------------------
# A fixed, reproducible subset chosen for headroom under a modest step budget:
# lower-difficulty tasks with short expert-time estimates, spread across
# categories, and (v1) internet-independent where possible. Pin by ID so the
# benchmark is stable even as upstream TB evolves.
TB_SUBSET_V1 = [
    "fix-git",                      # easy, software-engineering, 5min
    "prove-plus-comm",             # easy, software-engineering, 5min
    "cobol-modernization",         # easy, software-engineering, 20min
    "crack-7z-hash",               # medium, security, 5min
    "raman-fitting",               # medium, scientific-computing, 5min
    "mteb-leaderboard",            # medium, data-science, 5min
    "constraints-scheduling",      # medium, personal-assistant, 15min
    "kv-store-grpc",               # medium, software-engineering, 15min
    "mteb-retrieve",               # medium, data-science, 15min
    "pytorch-model-recovery",      # medium, model-training, 15min
    "merge-diff-arc-agi-task",     # medium, debugging, 20min
    "nginx-request-logging",       # medium, system-administration, 20min
    "openssl-selfsigned-cert",     # medium, security, 20min
    "polyglot-c-py",               # medium, software-engineering, 20min
    "vulnerable-secret",           # medium, security, 20min
    "hf-model-inference",          # medium, data-science, 20min
    "code-from-image",             # medium, software-engineering, 30min
    "extract-elf",                 # medium, file-operations, 30min
    "git-leak-recovery",           # medium, software-engineering, 30min
    "qemu-startup",                # medium, system-administration, 30min
]


def load_subset(tb_root: Path, subset: list[str] | None = None) -> list[TBTask]:
    """Load exactly the pinned subset, erroring loudly on any missing ID so we
    never silently benchmark on a different set than we reported."""
    ids = subset if subset is not None else TB_SUBSET_V1
    available = {d.name for d in Path(tb_root).iterdir() if (d / "task.toml").exists()}
    missing = [i for i in ids if i not in available]
    if missing:
        raise FileNotFoundError(
            f"tb-subset tasks not found in {tb_root}: {missing}. "
            "Clone github.com/harbor-framework/terminal-bench-2 and pass its path."
        )
    return [TBTask.load(Path(tb_root) / i) for i in ids]
