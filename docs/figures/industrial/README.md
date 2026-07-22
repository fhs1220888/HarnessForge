# HarnessForge industrial chart suite

These figures are generated from the committed snapshots in `docs/data/`, the
reported intervals in `EXPERIMENTS.md`, and the task-selection rules in
`src/harnessforge/eval/select.py`.

Run `python scripts/make_figures.py` after installing the development dependencies.
Every chart is emitted as a high-resolution PNG for Markdown and a scalable SVG for
reports.

| # | Chart | Evidence focus |
|---:|---|---|
| 01 | [Terminal-Bench Baseline](01-terminal-bench-baseline.png) | KPI and exit mix |
| 02 | [Per-Task Pass Rate](02-per-task-pass-rate.png) | Ranked task outcomes and failure class |
| 03 | [Why Runs Ended](03-exit-reason-breakdown.png) | Exit-reason distribution |
| 04 | [Native Headroom](04-native-headroom.png) | Budget-controlled headroom |
| 05 | [Harness Intervention Arc](05-intervention-arc.png) | Prediction, evidence, verdict |
| 06 | [Finish-Fix A/B](06-finishfix-ab.png) | Pass rate, cost, and finish behavior |
| 07 | [Selfverify Effects](07-selfverify-effects.png) | Effect estimates and intervals |
| 08 | [High-Signal Validation Set](08-high-signal-validation.png) | Targets, all tasks, and guards |
| 09 | [Proposal Calibration](09-proposal-calibration.png) | Predicted versus observed effects |
| 10 | [Efficiency Under Constraint](10-efficiency-under-constraint.png) | Descriptive cohort snapshots |
| 11 | [Failure Mining Pipeline](11-failure-mining-pipeline.png) | Trace-to-validation system flow |
| 12 | [Task Classification Matrix](12-task-classification.png) | Baseline class and validation role |
| 13 | [Trace Event Timeline](13-trace-event-timeline.png) | Schematic trace schema |
| 14 | [Reliability Surface](14-reliability-surface.png) | Categorical maturity assessment |
| 15 | [README Hero](15-readme-hero.png) | Baseline, budget pressure, and confirmed efficiency |

The `manifest.json` file records the generator, source set, palette, and output paths.
