"""Generate the full HarnessForge engineering-chart suite.

The figures are derived from committed snapshots under ``docs/data`` plus the
explicit comparison intervals recorded in ``EXPERIMENTS.md``.  Every chart is
written as a high-resolution PNG and a scalable SVG under
``docs/figures/industrial``.  Four legacy README filenames are refreshed too.

Usage:
    python scripts/make_figures.py
"""

from __future__ import annotations

import json
from pathlib import Path

from figures.common import INDUSTRIAL, ROOT, configure_style
from figures.experiments import (
    chart_efficiency_under_constraint,
    chart_finishfix_ab,
    chart_high_signal_validation,
    chart_proposal_calibration,
    chart_selfverify_effects,
)
from figures.results import (
    chart_exit_reason_breakdown,
    chart_intervention_arc,
    chart_native_headroom,
    chart_per_task_pass_rate,
    chart_terminal_bench_baseline,
)
from figures.systems import (
    chart_failure_mining_pipeline,
    chart_readme_hero,
    chart_reliability_surface,
    chart_task_classification,
    chart_trace_event_timeline,
)


CHARTS = [
    ("01-terminal-bench-baseline", "Terminal-Bench Baseline", chart_terminal_bench_baseline),
    ("02-per-task-pass-rate", "Per-Task Pass Rate", chart_per_task_pass_rate),
    ("03-exit-reason-breakdown", "Why Runs Ended", chart_exit_reason_breakdown),
    ("04-native-headroom", "Native Headroom", chart_native_headroom),
    ("05-intervention-arc", "Harness Intervention Arc", chart_intervention_arc),
    ("06-finishfix-ab", "Finish-Fix A/B", chart_finishfix_ab),
    ("07-selfverify-effects", "Selfverify Effects", chart_selfverify_effects),
    ("08-high-signal-validation", "High-Signal Validation Set", chart_high_signal_validation),
    ("09-proposal-calibration", "Proposal Calibration", chart_proposal_calibration),
    ("10-efficiency-under-constraint", "Efficiency Under Constraint", chart_efficiency_under_constraint),
    ("11-failure-mining-pipeline", "Failure Mining Pipeline", chart_failure_mining_pipeline),
    ("12-task-classification", "Task Classification Matrix", chart_task_classification),
    ("13-trace-event-timeline", "Trace Event Timeline", chart_trace_event_timeline),
    ("14-reliability-surface", "Harness Reliability Surface", chart_reliability_surface),
    ("15-readme-hero", "README Hero Summary", chart_readme_hero),
]


def _write_manifest(outputs: dict[str, list[Path]]) -> Path:
    manifest = {
        "schema_version": 1,
        "generator": "scripts/make_figures.py",
        "palette": {
            "ink": "#1a1a2e",
            "positive": "#2a9d8f",
            "failure": "#e94560",
            "warning": "#e9c46a",
            "neutral": "#8d99ae",
        },
        "sources": [
            "docs/data/tb_baseline_summary.json",
            "docs/data/tb_finishfix_summary.json",
            "docs/data/tb_selfverify_summary.json",
            "docs/data/tb_selfverify_extra_summary.json",
            "docs/data/tb_base_extra_summary.json",
            "docs/data/native_baseline_v4_summary.json",
            "docs/data/calibration.json",
            "runs/tb_baseline/results.jsonl",
            "runs/tb_base_extra/results.jsonl",
            "runs/tb_finishfix/results.jsonl",
            "runs/tb_selfverify/results.jsonl",
            "runs/tb_selfverify_extra/results.jsonl",
            "EXPERIMENTS.md",
            "src/harnessforge/eval/select.py",
        ],
        "charts": [
            {
                "slug": slug,
                "title": title,
                "files": [str(path.relative_to(ROOT)) for path in outputs[slug]],
            }
            for slug, title, _ in CHARTS
        ],
    }
    INDUSTRIAL.mkdir(parents=True, exist_ok=True)
    path = INDUSTRIAL / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


def main() -> None:
    configure_style()
    outputs: dict[str, list[Path]] = {}
    for slug, _, render in CHARTS:
        outputs[slug] = render(slug)
    manifest = _write_manifest(outputs)
    print(f"wrote {len(CHARTS)} charts (PNG + SVG) to {INDUSTRIAL.relative_to(ROOT)}")
    print(f"wrote manifest to {manifest.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
