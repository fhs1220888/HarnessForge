"""Audit and score the final causal comparison for a self-harness campaign.

This wrapper is deliberately stricter than ``eval.compare``. It first proves
that control and treatment used the same benchmark protocol, task material,
budgets, and repeat counts, then computes paired effects. A positive point
estimate alone can never set the causal claim to ``confirmed``.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from ..eval.compare import SKIP, compare
from ..eval.counterfactual import _write_json_atomic


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_rows(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "results.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"missing results: {path}")
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _only(values: set[Any], label: str) -> Any:
    if len(values) != 1:
        raise ValueError(f"mixed {label}: {sorted(values, key=str)}")
    return next(iter(values))


def _manifest_protocol(manifest: dict[str, Any]) -> dict[str, Any]:
    extra = manifest.get("extra", {})
    return {
        "benchmark": manifest.get("benchmark"),
        "agent_model": manifest.get("agent_model"),
        "provider": manifest.get("provider", "anthropic"),
        "max_steps": manifest.get("max_steps"),
        "temperature": manifest.get("temperature"),
        "seed": manifest.get("seed"),
        "max_output_tokens_per_call": extra.get(
            "max_output_tokens_per_call", manifest.get("max_output_tokens")
        ),
        "max_cost_usd_per_task": extra.get("max_cost_usd_per_task"),
        "terminal_bench_revision": extra.get("terminal_bench_revision"),
    }


def _arm(run_dirs: list[Path], label: str) -> dict[str, Any]:
    if not run_dirs:
        raise ValueError(f"{label} arm has no run directories")
    manifests = [_read_json(Path(run_dir) / "manifest.json") for run_dir in run_dirs]
    rows = [row for run_dir in run_dirs for row in _read_rows(Path(run_dir))]
    skipped = [row for row in rows if row.get("exit_reason") in SKIP]
    if skipped:
        raise ValueError(
            f"{label} arm has {len(skipped)} infra/api error outcome(s); resume first"
        )
    run_ids = [row.get("run_id") for row in rows]
    if None in run_ids or len(set(run_ids)) != len(run_ids):
        raise ValueError(f"{label} arm has missing or duplicate run_id values")

    protocol_rows = [_manifest_protocol(manifest) for manifest in manifests]
    protocol = protocol_rows[0]
    for candidate in protocol_rows[1:]:
        if candidate != protocol:
            raise ValueError(f"mixed evaluation protocol inside {label} arm")

    declared_tasks = {
        task for manifest in manifests for task in manifest.get("task_ids", [])
    }
    observed_tasks = {row["task_id"] for row in rows}
    if declared_tasks != observed_tasks:
        raise ValueError(
            f"{label} manifest/result task mismatch: declared={sorted(declared_tasks)}, "
            f"observed={sorted(observed_tasks)}"
        )
    counts = Counter(row["task_id"] for row in rows)
    repeats = _only(set(counts.values()), f"{label} repeats per task")

    manifest_versions = {
        manifest.get("harness_version") for manifest in manifests
    }
    row_versions = {row.get("harness_version") for row in rows}
    harness_version = _only(
        manifest_versions | row_versions, f"{label} harness versions"
    )

    # Matching shard signatures make the content hash useful even when an arm
    # is split across several task/repeat directories.
    shard_content = sorted(
        (
            tuple(sorted(manifest.get("task_ids", []))),
            manifest.get("suite_content_hash", ""),
        )
        for manifest in manifests
    )
    declared_images: dict[str, str] = {}
    for manifest in manifests:
        for task, image in manifest.get("extra", {}).get(
            "declared_docker_images", {}
        ).items():
            existing = declared_images.get(task)
            if existing is not None and existing != image:
                raise ValueError(f"mixed image declarations for task {task} in {label}")
            declared_images[task] = image

    return {
        "run_dirs": [str(Path(path)) for path in run_dirs],
        "protocol": protocol,
        "task_ids": sorted(observed_tasks),
        "task_count": len(observed_tasks),
        "repeats_per_task": repeats,
        "scored_runs": len(rows),
        "harness_version": harness_version,
        "shard_content": shard_content,
        "declared_docker_images": declared_images,
        "rows": rows,
    }


def build_causal_proof(
    control_dirs: list[Path],
    treatment_dirs: list[Path],
    *,
    minimum_tasks: int = 20,
    minimum_repeats: int = 2,
) -> dict[str, Any]:
    """Validate a matched experiment and gate a causal pass-rate claim."""
    if minimum_tasks <= 0 or minimum_repeats <= 0:
        raise ValueError("minimum_tasks and minimum_repeats must be positive")
    control = _arm(control_dirs, "control")
    treatment = _arm(treatment_dirs, "treatment")
    terminal_bench = "terminal-bench" in str(control["protocol"]["benchmark"]).lower()
    required_protocol_fields = (
        "benchmark",
        "agent_model",
        "provider",
        "max_steps",
        "max_output_tokens_per_call",
    )

    checks = {
        "required_protocol_fields_present": all(
            control["protocol"].get(field) is not None
            and treatment["protocol"].get(field) is not None
            for field in required_protocol_fields
        ),
        "evaluation_protocol_equal": control["protocol"] == treatment["protocol"],
        "task_set_equal": control["task_ids"] == treatment["task_ids"],
        "task_content_equal": control["shard_content"] == treatment["shard_content"],
        "task_content_hashes_present": all(
            content_hash
            for arm in (control, treatment)
            for _, content_hash in arm["shard_content"]
        ),
        "container_images_equal": (
            control["declared_docker_images"] == treatment["declared_docker_images"]
        ),
        "terminal_bench_revision_pinned": (
            not terminal_bench
            or bool(control["protocol"].get("terminal_bench_revision"))
        ),
        "terminal_bench_images_pinned": (
            not terminal_bench
            or set(control["declared_docker_images"]) == set(control["task_ids"])
        ),
        "repeat_count_equal": (
            control["repeats_per_task"] == treatment["repeats_per_task"]
        ),
        "harness_versions_differ": (
            control["harness_version"] != treatment["harness_version"]
        ),
    }
    protocol_match = all(checks.values())
    if not protocol_match:
        failed = [name for name, passed in checks.items() if not passed]
        raise ValueError(f"causal comparison protocol mismatch: {', '.join(failed)}")

    effects = compare(control_dirs, treatment_dirs)
    sample_requirements = {
        "minimum_tasks": minimum_tasks,
        "observed_tasks": control["task_count"],
        "minimum_repeats_per_arm": minimum_repeats,
        "observed_repeats_per_arm": control["repeats_per_task"],
        "met": (
            control["task_count"] >= minimum_tasks
            and control["repeats_per_task"] >= minimum_repeats
        ),
    }
    pass_ci_positive = float(effects["pass_rate"]["ci_low"]) > 0
    by_task: dict[str, dict[str, list[bool]]] = defaultdict(
        lambda: {"control": [], "treatment": []}
    )
    for arm_name, arm in (("control", control), ("treatment", treatment)):
        for row in arm["rows"]:
            by_task[row["task_id"]][arm_name].append(bool(row["passed"]))
    regressed_tasks = sorted(
        task
        for task, outcomes in by_task.items()
        if sum(outcomes["treatment"]) / len(outcomes["treatment"])
        < sum(outcomes["control"]) / len(outcomes["control"])
    )

    return {
        "schema_version": 1,
        "experiment": "self_harness_final_causal_comparison",
        "control": {key: value for key, value in control.items() if key != "rows"},
        "treatment": {
            key: value for key, value in treatment.items() if key != "rows"
        },
        "protocol_checks": checks,
        "protocol_match": protocol_match,
        "sample_requirements": sample_requirements,
        "paired_effects": effects,
        "diagnostics": {
            "tasks_with_lower_treatment_pass_rate": regressed_tasks,
            "regressed_task_count": len(regressed_tasks),
        },
        "decision": {
            "pass_rate_ci_lower_bound_above_zero": pass_ci_positive,
            "confirmed_causal_pass_rate_uplift": (
                protocol_match and sample_requirements["met"] and pass_ci_positive
            ),
            "reason": (
                "matched protocol, sufficient predeclared sample, and paired 95% "
                "interval lower bound above zero"
                if sample_requirements["met"] and pass_ci_positive
                else "causal uplift gate not met"
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--control", nargs="+", type=Path, required=True)
    parser.add_argument("--treatment", nargs="+", type=Path, required=True)
    parser.add_argument("--minimum-tasks", type=int, default=20)
    parser.add_argument("--minimum-repeats", type=int, default=2)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    proof = build_causal_proof(
        args.control,
        args.treatment,
        minimum_tasks=args.minimum_tasks,
        minimum_repeats=args.minimum_repeats,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(args.out, proof)
    print(json.dumps(proof, indent=2))


if __name__ == "__main__":
    main()
