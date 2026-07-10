"""Loads the evolvable harness components and snapshots their version.

The harness "genome" is the content of harness/*.{md,yaml}. A HarnessConfig is
immutable for the duration of a run; its content hash is written into every trace
so any result can be attributed to an exact harness version.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

HARNESS_DIR = Path(__file__).resolve().parents[2] / "harness"

EVOLVABLE_COMPONENTS = [
    "system_prompt.md",
    "tool_descriptions.yaml",
    "loop_policy.yaml",
]


@dataclass(frozen=True)
class HarnessConfig:
    system_prompt: str
    tool_descriptions: dict[str, Any]
    loop_policy: dict[str, Any]
    version: str  # short content hash across all evolvable components

    @classmethod
    def load(cls, harness_dir: Path = HARNESS_DIR) -> "HarnessConfig":
        raw: dict[str, str] = {}
        for name in EVOLVABLE_COMPONENTS:
            raw[name] = (harness_dir / name).read_text(encoding="utf-8")
        version = hashlib.sha256(
            "\x00".join(raw[n] for n in EVOLVABLE_COMPONENTS).encode()
        ).hexdigest()[:12]
        return cls(
            system_prompt=raw["system_prompt.md"],
            tool_descriptions=yaml.safe_load(raw["tool_descriptions.yaml"]),
            loop_policy=yaml.safe_load(raw["loop_policy.yaml"]),
            version=version,
        )

    def policy(self, dotted: str, default: Any = None) -> Any:
        """policy('limits.max_steps') -> 30"""
        node: Any = self.loop_policy
        for key in dotted.split("."):
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node
