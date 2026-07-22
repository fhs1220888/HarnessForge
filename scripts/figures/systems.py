"""Charts 11-15: system, allocation, trace, maturity, and README summary."""

from __future__ import annotations

from matplotlib import pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Polygon, Rectangle

from .common import (
    AMBER,
    BG,
    CORAL,
    GRAY,
    GRID,
    INK,
    LIGHT_GRAY,
    TEAL,
    WHITE,
    add_chart_title,
    add_source,
    configure_style,
    save_figure,
    style_axis,
)
from .data import (
    SELFVERIFY_EFFECTS,
    TB_CAPABILITY_LIMITED,
    TB_HARNESS_FIXABLE,
    TB_REGRESSION_GUARDS,
    baseline,
    calibration,
)


def _rounded_box(
    ax,
    center: tuple[float, float],
    width: float,
    height: float,
    *,
    facecolor: str = WHITE,
    edgecolor: str = LIGHT_GRAY,
    linewidth: float = 1.0,
    radius: float = 1.0,
    linestyle: str = "-",
    zorder: int = 2,
):
    """Draw a restrained process/event node in data coordinates."""
    x, y = center
    patch = FancyBboxPatch(
        (x - width / 2, y - height / 2),
        width,
        height,
        boxstyle=f"round,pad=0.18,rounding_size={radius}",
        facecolor=facecolor,
        edgecolor=edgecolor,
        linewidth=linewidth,
        linestyle=linestyle,
        zorder=zorder,
    )
    ax.add_patch(patch)
    return patch


def chart_failure_mining_pipeline(slug: str):
    """Engineering flow from recorded eval evidence to a guarded decision."""
    configure_style()
    b = baseline()
    rows = calibration()
    n_merged = sum(bool(row.get("merged")) for row in rows)

    fig = plt.figure(figsize=(15.0, 5.0))
    ax = fig.add_axes([0.035, 0.14, 0.93, 0.67])
    ax.set_xlim(0, 106)
    ax.set_ylim(0, 100)
    ax.axis("off")

    add_chart_title(
        fig,
        "From Failed Runs To Harness Changes",
        "Evaluation evidence stays attached to its source stage before a guarded accept / reject decision.",
        x=0.045,
    )

    scored = int(b["n_scored"])
    max_steps = int(b["exit_reasons"].get("max_steps", 0))
    stages = [
        ("Eval runner", f"{scored} scored runs\n{b['n_tasks']} tasks · {b['repeats']} repeats"),
        ("JSONL traces", "tokens · cost\nexit reason"),
        ("Weakness mining", f"{max_steps}/{scored} runs\nhit max_steps"),
        ("Failure patterns", "cluster recurring\nfailure modes"),
        ("Proposal generation", "predicted Δ\ncomponent diff"),
        ("Validation gate", "targets + guards\npaired repeats"),
        ("Calibration table", "observed Δ\nbackfill proposal"),
    ]
    centers = [6.5, 19.0, 31.5, 44.0, 56.5, 69.0, 81.5]
    node_width = 10.6
    node_height = 31.0
    node_y = 55.0

    for index, ((title, detail), center_x) in enumerate(zip(stages, centers), start=1):
        _rounded_box(ax, (center_x, node_y), node_width, node_height)
        ax.text(
            center_x,
            node_y + 5.2,
            title,
            ha="center",
            va="center",
            fontsize=8.9,
            fontweight=400,
            color=INK,
            zorder=3,
        )
        ax.text(
            center_x,
            node_y - 5.2,
            detail,
            ha="center",
            va="center",
            fontsize=7.8,
            color=GRAY,
            linespacing=1.35,
            zorder=3,
        )
        ax.text(
            center_x,
            node_y + node_height / 2 + 5.4,
            f"{index:02d}",
            ha="center",
            va="center",
            fontsize=7.4,
            fontweight=400,
            color=GRAY,
        )

    for left, right in zip(centers[:-1], centers[1:]):
        ax.add_patch(
            FancyArrowPatch(
                (left + node_width / 2 + 0.4, node_y),
                (right - node_width / 2 - 0.4, node_y),
                arrowstyle="-|>",
                mutation_scale=9,
                linewidth=1.0,
                color=GRAY,
                zorder=1,
            )
        )

    diamond_x = 91.1
    diamond = Polygon(
        [
            (diamond_x, node_y + 10.5),
            (diamond_x + 5.0, node_y),
            (diamond_x, node_y - 10.5),
            (diamond_x - 5.0, node_y),
        ],
        closed=True,
        facecolor=WHITE,
        edgecolor=INK,
        linewidth=1.0,
        zorder=2,
    )
    ax.add_patch(diamond)
    ax.text(diamond_x, node_y, "MERGE?", ha="center", va="center", fontsize=8.0, fontweight=400)
    ax.add_patch(
        FancyArrowPatch(
            (centers[-1] + node_width / 2 + 0.4, node_y),
            (diamond_x - 5.4, node_y),
            arrowstyle="-|>",
            mutation_scale=9,
            linewidth=1.0,
            color=GRAY,
        )
    )

    outcomes = [
        (72.0, "ACCEPT", "effect threshold met\nno regression", TEAL),
        (38.0, "REJECT", "noise · regression\nunderpowered", CORAL),
    ]
    outcome_x = 101.0
    for outcome_y, label, detail, color in outcomes:
        _rounded_box(
            ax,
            (outcome_x, outcome_y),
            9.0,
            20.0,
            facecolor=WHITE,
            edgecolor=color,
            linewidth=1.3,
            radius=1.0,
        )
        ax.text(outcome_x, outcome_y + 3.7, label, ha="center", va="center", fontsize=8.2, fontweight=400)
        ax.text(outcome_x, outcome_y - 3.8, detail, ha="center", va="center", fontsize=6.9, color=GRAY, linespacing=1.25)
        ax.add_patch(
            FancyArrowPatch(
                (diamond_x + 3.8, node_y + (3.0 if outcome_y > node_y else -3.0)),
                (outcome_x - 4.8, outcome_y),
                arrowstyle="-|>",
                mutation_scale=8,
                linewidth=1.0,
                color=color,
                connectionstyle="arc3,rad=0.08" if outcome_y > node_y else "arc3,rad=-0.08",
            )
        )

    ax.text(
        81.5,
        17.5,
        f"Current calibration: {len(rows)} proposals · {n_merged} merged",
        ha="center",
        va="center",
        fontsize=8.0,
        color=GRAY,
    )
    add_source(
        fig,
        "Sources: docs/data/tb_baseline_summary.json · docs/data/calibration.json · process schema in src/harnessforge/selfharness/",
        x=0.045,
    )
    return save_figure(fig, slug)


def chart_task_classification(slug: str):
    """Overlapping baseline classes and validation roles for all 20 TB tasks."""
    configure_style()
    b = baseline()
    per_task = b["per_task"]

    always_pass = sorted(task for task, outcomes in per_task.items() if all(outcomes))
    borderline = sorted(task for task, outcomes in per_task.items() if any(outcomes) and not all(outcomes))
    always_fail = {task for task, outcomes in per_task.items() if not any(outcomes)}
    harness_fixable = sorted(always_fail & TB_HARNESS_FIXABLE)
    capability_limited = sorted(always_fail & TB_CAPABILITY_LIMITED)
    unclassified = sorted(always_fail - TB_HARNESS_FIXABLE - TB_CAPABILITY_LIMITED)
    if unclassified:
        capability_limited.extend(unclassified)

    groups = [
        ("ALWAYS PASS", always_pass),
        ("BORDERLINE", borderline),
        ("HARNESS-FIXABLE FAILURES", harness_fixable),
        ("CAPABILITY-LIMITED FAILURES", capability_limited),
    ]

    rows: list[tuple[str, str, float]] = []
    group_headers: list[tuple[str, float]] = []
    cursor = 0.0
    for group_name, tasks in groups:
        group_headers.append((group_name, cursor))
        cursor += 0.72
        for task in tasks:
            rows.append((task, group_name, cursor))
            cursor += 1.0
        cursor += 0.42

    fig = plt.figure(figsize=(13.2, 9.4))
    # Leave a full title/subtitle band above the top-positioned column headers.
    ax = fig.add_axes([0.31, 0.105, 0.65, 0.70])
    ax.set_xlim(-0.72, 4.55)
    ax.set_ylim(cursor - 0.1, -0.45)

    add_chart_title(
        fig,
        "Where Evaluation Budget Should Go",
        "Observed baseline class and validation role can overlap · 7 selected targets + 3 always-pass guards.",
        x=0.055,
    )

    column_labels = [
        "Always\npass",
        "Borderline",
        "Harness-fixable\nfailure",
        "Capability-limited\nfailure",
        "Regression\nguard",
    ]
    ax.set_xticks(range(5))
    ax.set_xticklabels(column_labels, fontsize=9.0, fontweight=400)
    ax.xaxis.tick_top()
    ax.tick_params(axis="x", pad=12, length=0)
    ax.set_yticks([y for _, _, y in rows])
    ax.set_yticklabels([task for task, _, _ in rows], fontsize=8.5)
    ax.tick_params(axis="y", pad=12, length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)

    for x in range(5):
        ax.axvline(x, color=GRID, linewidth=0.8, zorder=0)
    for _, _, y in rows:
        ax.axhline(y, color=GRID, linewidth=0.55, alpha=0.75, zorder=0)

    y_by_task = {task: y for task, _, y in rows}
    target_tasks = set(borderline) | set(harness_fixable)
    guards = set(always_pass) & TB_REGRESSION_GUARDS

    for task in always_pass:
        y = y_by_task[task]
        ax.scatter(0, y, s=58, marker="s", color=GRAY, edgecolor=WHITE, linewidth=0.8, zorder=3)
    for task in borderline:
        y = y_by_task[task]
        ax.scatter(1, y, s=66, marker="o", color=AMBER, edgecolor=INK, linewidth=0.7, zorder=3)
    for task in harness_fixable:
        y = y_by_task[task]
        ax.scatter(2, y, s=66, marker="o", color=TEAL, edgecolor=WHITE, linewidth=0.8, zorder=3)
    for task in capability_limited:
        y = y_by_task[task]
        ax.scatter(3, y, s=70, marker="X", color=CORAL, edgecolor=WHITE, linewidth=0.8, zorder=3)
    for task in sorted(guards):
        y = y_by_task[task]
        ax.scatter(4, y, s=76, marker="D", facecolor=BG, edgecolor=TEAL, linewidth=1.5, zorder=3)
    for task in sorted(target_tasks):
        y = y_by_task[task]
        ax.plot([-0.63, -0.63], [y - 0.31, y + 0.31], color=TEAL, linewidth=3.0, solid_capstyle="round", zorder=4)

    for group_name, header_y in group_headers:
        ax.text(
            -0.055,
            header_y,
            group_name,
            transform=ax.get_yaxis_transform(),
            ha="right",
            va="center",
            fontsize=7.3,
            fontweight=400,
            color=GRAY,
            clip_on=False,
        )

    legend_handles = [
        Line2D([0], [0], color=TEAL, linewidth=3, label="selected validation target"),
        Line2D([0], [0], marker="D", linestyle="", markerfacecolor=BG, markeredgecolor=TEAL, label="regression guard"),
        Line2D([0], [0], marker="X", linestyle="", color=CORAL, label="excluded: capability-limited"),
    ]
    ax.legend(
        handles=legend_handles,
        loc="lower center",
        bbox_to_anchor=(0.5, -0.095),
        ncol=3,
        fontsize=8.1,
        handlelength=1.8,
        columnspacing=2.0,
    )
    add_source(
        fig,
        "Sources: docs/data/tb_baseline_summary.json · task roles from scripts/figures/data.py (mirrors eval/select.py)",
        x=0.055,
    )
    return save_figure(fig, slug)


def _event_box(
    ax,
    x: float,
    y: float,
    label: str,
    *,
    edgecolor: str = LIGHT_GRAY,
    facecolor: str = WHITE,
    linestyle: str = "-",
    width: float = 10.2,
    height: float = 8.5,
):
    _rounded_box(
        ax,
        (x, y),
        width,
        height,
        facecolor=facecolor,
        edgecolor=edgecolor,
        linewidth=1.1,
        radius=0.9,
        linestyle=linestyle,
        zorder=3,
    )
    ax.text(x, y, label, ha="center", va="center", fontsize=8.0, fontweight=400, color=INK, zorder=4)


def chart_trace_event_timeline(slug: str):
    """Schematic event-schema timeline without fabricated measured values."""
    configure_style()
    fig = plt.figure(figsize=(14.2, 5.4))
    ax = fig.add_axes([0.045, 0.14, 0.92, 0.68])
    ax.set_xlim(0, 100)
    ax.set_ylim(-30, 43)
    ax.axis("off")

    add_chart_title(
        fig,
        "One Run As Structured Events",
        "SCHEMATIC — ordinal event schema, not a recorded duration; no timestamps, token totals, or costs are fabricated.",
        x=0.05,
    )

    lane_x = 1.5
    ax.text(lane_x, 31.5, "TELEMETRY", fontsize=7.1, fontweight=400, color=GRAY, va="center")
    ax.text(
        lane_x,
        8.0,
        "EVENT\nSTREAM",
        fontsize=7.1,
        fontweight=400,
        color=GRAY,
        va="center",
        ha="left",
        linespacing=1.1,
    )
    ax.text(lane_x, -11.5, "OPTIONAL / OUTCOME", fontsize=7.1, fontweight=400, color=GRAY, va="center")
    ax.text(lane_x, -25.0, "STEP SEMANTICS", fontsize=7.1, fontweight=400, color=GRAY, va="center")

    # A flat telemetry rail communicates accumulation without inventing a curve.
    ax.add_patch(
        FancyArrowPatch((14, 31.5), (95, 31.5), arrowstyle="-|>", mutation_scale=9, linewidth=1.0, color=GRAY)
    )
    ax.text(34, 34.1, "llm_response adds tokens_in + tokens_out + cost_usd", fontsize=7.8, color=INK, ha="center")
    ax.text(94.5, 34.1, "Σ tokens · Σ cost", fontsize=8.2, fontweight=400, color=INK, ha="right")

    # The repeated request/response/tool core is a loop, not a fixed one-pass sequence.
    loop_region = FancyBboxPatch(
        (14.2, 0.2),
        49.8,
        16.0,
        boxstyle="round,pad=0.2,rounding_size=1.2",
        facecolor=WHITE,
        edgecolor=LIGHT_GRAY,
        linewidth=0.9,
        linestyle="--",
        zorder=0,
    )
    ax.add_patch(loop_region)
    ax.text(39.1, 18.8, "agent loop · repeats as needed", ha="center", va="center", fontsize=7.6, color=GRAY)

    core_events = [
        (12, "run_start"),
        (24, "llm_request"),
        (36, "llm_response"),
        (48, "tool_call"),
        (60, "tool_result"),
        (92, "termination"),
    ]
    for x, label in core_events:
        edge = INK if label in {"run_start", "termination"} else GRAY
        _event_box(ax, x, 8.0, label, edgecolor=edge)

    for (left_x, _), (right_x, _) in zip(core_events[:4], core_events[1:5]):
        ax.add_patch(
            FancyArrowPatch(
                (left_x + 5.4, 8.0),
                (right_x - 5.4, 8.0),
                arrowstyle="-|>",
                mutation_scale=8,
                linewidth=1.0,
                color=GRAY,
                zorder=2,
            )
        )
    ax.add_patch(
        FancyArrowPatch((65.5, 8.0), (86.3, 8.0), arrowstyle="-|>", mutation_scale=8, linewidth=1.0, color=GRAY)
    )
    ax.text(76.0, 8.0, "⋯", ha="center", va="center", fontsize=17, color=GRAY)
    ax.add_patch(
        FancyArrowPatch(
            (60, 3.2),
            (24, 3.2),
            arrowstyle="-|>",
            mutation_scale=8,
            linewidth=0.9,
            color=GRAY,
            connectionstyle="arc3,rad=-0.30",
            zorder=1,
        )
    )
    ax.text(42, -0.2, "next iteration", ha="center", va="center", fontsize=7.2, color=GRAY)

    optional_events = [
        (24, -11.5, "memory_write", TEAL),
        (41, -11.5, "compaction", AMBER),
        (59, -11.5, "test_run", TEAL),
        (76, -11.5, "validation_error", CORAL),
    ]
    for x, y, label, color in optional_events:
        _event_box(ax, x, y, label, edgecolor=color, linestyle="--" if label != "test_run" else "-")

    # Dotted connectors mean optional emission, not elapsed-time placement.
    connector_pairs = [((24, -7.0), (48, 3.6)), ((41, -7.0), (36, 3.6)), ((59, -7.0), (60, 3.6)), ((76, -7.0), (48, 3.6))]
    for start, end in connector_pairs:
        ax.add_patch(
            FancyArrowPatch(
                start,
                end,
                arrowstyle="-",
                linewidth=0.8,
                linestyle=":",
                color=GRAY,
                connectionstyle="arc3,rad=0.08",
                zorder=1,
            )
        )
    ax.text(59, -17.6, "PASS / FAIL", ha="center", va="center", fontsize=7.0, color=GRAY)
    ax.text(92, 0.7, "finished_done", ha="center", va="center", fontsize=7.3, fontweight=400, color=TEAL)
    ax.text(92, -4.0, "budget / error exit", ha="center", va="center", fontsize=7.3, fontweight=400, color=CORAL)

    ax.add_patch(
        FancyArrowPatch((14, -25.0), (95, -25.0), arrowstyle="-|>", mutation_scale=9, linewidth=1.0, color=GRAY)
    )
    ax.text(38, -22.3, "event.step: 0 → … → N", ha="center", va="center", fontsize=7.8, color=INK)
    ax.text(75, -22.3, "agent iteration = count(llm_request)", ha="center", va="center", fontsize=7.8, color=INK)

    add_source(
        fig,
        "Schema: src/harnessforge/trace.py · Values intentionally omitted; measured timing and cumulative totals require a concrete JSONL trace.",
        x=0.05,
    )
    return save_figure(fig, slug)


def chart_reliability_surface(slug: str):
    """Categorical maturity matrix; deliberately avoids synthetic radar scores."""
    configure_style()
    maturity_columns = ["Basic", "Basic+", "Solid", "Near-production"]
    rows = [
        ("Evaluation & observability", "Near-production", "JSONL · replay · bootstrap/Wilson CIs"),
        ("Constraints & recovery", "Near-production", "budgets · retry · arg validation"),
        ("Tool system", "Solid", "simple scope · 6 tools"),
        ("Orchestration", "Basic+", "single loop · crash-safe resume"),
        ("Context management", "Basic+", "deterministic compaction"),
        ("State & memory", "Solid", "episode-scoped · replayable"),
    ]
    status_x = {label: index for index, label in enumerate(maturity_columns)}
    status_style = {
        "Basic+": (AMBER, "s"),
        "Solid": (TEAL, "o"),
        "Near-production": (TEAL, "D"),
    }

    fig = plt.figure(figsize=(11.8, 5.3))
    ax = fig.add_axes([0.28, 0.16, 0.68, 0.65])
    ax.set_xlim(-0.55, 6.5)
    ax.set_ylim(len(rows) - 0.45, -0.55)

    add_chart_title(
        fig,
        "Harness Reliability Surface",
        "Categorical engineering self-assessment · no numeric score or radar area is implied.",
        x=0.055,
    )

    ax.set_xticks(range(4))
    ax.set_xticklabels(maturity_columns, fontsize=9.0, fontweight=400)
    ax.xaxis.tick_top()
    ax.tick_params(axis="x", pad=12, length=0)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([row[0] for row in rows], fontsize=9.1)
    ax.tick_params(axis="y", pad=12, length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)

    for row_y in range(len(rows)):
        for col_x in range(4):
            ax.add_patch(
                Rectangle(
                    (col_x - 0.44, row_y - 0.34),
                    0.88,
                    0.68,
                    facecolor=WHITE,
                    edgecolor=GRID,
                    linewidth=0.8,
                    zorder=0,
                )
            )

    for row_y, (_, status, qualifier) in enumerate(rows):
        col_x = status_x[status]
        color, marker = status_style[status]
        ax.add_patch(
            Rectangle(
                (col_x - 0.44, row_y - 0.34),
                0.88,
                0.68,
                facecolor=color,
                edgecolor=color,
                linewidth=1.0,
                alpha=0.18 if status != "Basic+" else 0.25,
                zorder=1,
            )
        )
        ax.scatter(col_x, row_y, s=58, marker=marker, color=color, edgecolor=WHITE, linewidth=0.9, zorder=3)
        ax.text(4.45, row_y, qualifier, ha="left", va="center", fontsize=8.2, color=GRAY)

    ax.text(4.45, -0.72, "SCOPE / EVIDENCE", ha="left", va="center", fontsize=7.5, fontweight=400, color=GRAY)
    legend_handles = [
        Line2D([0], [0], marker="s", linestyle="", markerfacecolor=AMBER, markeredgecolor=WHITE, label="Basic+"),
        Line2D([0], [0], marker="o", linestyle="", markerfacecolor=TEAL, markeredgecolor=WHITE, label="Solid"),
        Line2D([0], [0], marker="D", linestyle="", markerfacecolor=TEAL, markeredgecolor=WHITE, label="Near-production"),
    ]
    ax.legend(
        handles=legend_handles,
        loc="lower left",
        bbox_to_anchor=(0.0, -0.19),
        ncol=3,
        fontsize=8.0,
        columnspacing=1.7,
        handletextpad=0.5,
    )
    add_source(
        fig,
        "Source: EXPERIMENTS.md · Qualitative self-assessment; qualifiers describe scope and evidence, not additional maturity levels.",
        x=0.055,
    )
    return save_figure(fig, slug)


def chart_readme_hero(slug: str):
    """Wide, compact README summary of baseline pressure and verified efficiency."""
    configure_style()
    b = baseline()
    pass_effect = SELFVERIFY_EFFECTS["pass_rate"]
    steps_effect = SELFVERIFY_EFFECTS["steps_per_run"]
    n_scored = int(b["n_scored"])
    pass_count = round(float(b["pass_rate"]) * n_scored)

    fig = plt.figure(figsize=(14.4, 4.8))
    grid = fig.add_gridspec(
        1,
        3,
        left=0.055,
        right=0.97,
        bottom=0.17,
        top=0.77,
        wspace=0.30,
        width_ratios=[0.92, 1.28, 1.72],
    )
    ax_kpi = fig.add_subplot(grid[0, 0])
    ax_exit = fig.add_subplot(grid[0, 1])
    ax_effect = fig.add_subplot(grid[0, 2])

    add_chart_title(
        fig,
        "HarnessForge — Evidence Under Constraint",
        f"Terminal-Bench 2.0 subset · {b['n_tasks']} tasks · {b['tb_max_steps']}-step budget · measured effects, not aspiration",
        x=0.055,
    )

    ax_kpi.axis("off")
    ax_kpi.text(0.0, 0.96, "BASELINE", transform=ax_kpi.transAxes, fontsize=9.0, fontweight=400, color=GRAY, va="top")
    ax_kpi.text(
        0.0,
        0.76,
        f"{b['pass_rate']:.1%}",
        transform=ax_kpi.transAxes,
        fontsize=34,
        fontweight=400,
        color=INK,
        va="top",
    )
    ax_kpi.text(0.0, 0.48, "pass rate", transform=ax_kpi.transAxes, fontsize=10.5, color=INK, va="top")
    ax_kpi.text(
        0.0,
        0.35,
        f"{pass_count} / {n_scored} scored runs",
        transform=ax_kpi.transAxes,
        fontsize=9.5,
        color=GRAY,
        va="top",
    )
    ax_kpi.plot([0.0, 0.78], [0.23, 0.23], transform=ax_kpi.transAxes, color=LIGHT_GRAY, linewidth=1.0)
    ax_kpi.plot([0.0, 0.78 * float(b["pass_rate"])], [0.23, 0.23], transform=ax_kpi.transAxes, color=TEAL, linewidth=4.0)
    ax_kpi.text(0.0, 0.12, "External verification · 2 repeats", transform=ax_kpi.transAxes, fontsize=8.8, color=GRAY, va="top")

    exit_order = ["max_steps", "finished_done", "max_tokens"]
    exit_labels = ["max_steps", "finished_done", "max_tokens"]
    exit_counts = [int(b["exit_reasons"].get(reason, 0)) for reason in exit_order]
    exit_colors = [CORAL, TEAL, AMBER]
    y_positions = [2, 1, 0]
    bars = ax_exit.barh(y_positions, exit_counts, color=exit_colors, height=0.48, zorder=3)
    ax_exit.set_yticks(y_positions)
    ax_exit.set_yticklabels(exit_labels, fontsize=9.4)
    ax_exit.set_xlim(0, n_scored)
    ax_exit.set_xticks([0, 10, 20, 30, 40])
    ax_exit.set_xlabel("runs", fontsize=9.0)
    ax_exit.set_title("Why runs ended · step cap dominates", loc="left", fontsize=11.0, fontweight=400, pad=12)
    style_axis(ax_exit, grid="x", keep=("bottom",))
    for bar, count in zip(bars, exit_counts):
        share = count / n_scored
        ax_exit.text(
            min(count + 0.7, n_scored - 0.3),
            bar.get_y() + bar.get_height() / 2,
            f"{count} · {share:.1%}",
            ha="left" if count < n_scored - 4 else "right",
            va="center",
            fontsize=9.0,
            fontweight=400,
            color=INK,
        )

    metric_rows = [
        ("Pass rate (pp)", pass_effect, GRAY, "o", "CI crosses 0"),
        ("Steps/run (%)", steps_effect, TEAL, "s", "CI excludes 0"),
    ]
    metric_y = [1, 0]
    for y, (label, effect, color, marker, inference) in zip(metric_y, metric_rows):
        delta = float(effect["delta"]) * 100
        lo = float(effect["lo"]) * 100
        hi = float(effect["hi"]) * 100
        ax_effect.plot([lo, hi], [y, y], color=color, linewidth=2.0, zorder=3)
        ax_effect.plot([lo, lo], [y - 0.08, y + 0.08], color=color, linewidth=1.2, zorder=3)
        ax_effect.plot([hi, hi], [y - 0.08, y + 0.08], color=color, linewidth=1.2, zorder=3)
        ax_effect.scatter(delta, y, s=58, marker=marker, color=color, edgecolor=WHITE, linewidth=0.9, zorder=4)
        unit = "pp" if "Pass" in label else "%"
        sign = "+" if delta > 0 else ""
        ax_effect.text(
            -14.7,
            y + 0.29,
            f"{sign}{delta:.1f}{unit}  [{lo:+.1f}, {hi:+.1f}]",
            ha="left",
            va="center",
            fontsize=9.0,
            color=INK,
        )
        ax_effect.text(
            0.95,
            y + 0.16,
            inference,
            transform=ax_effect.get_yaxis_transform(),
            ha="right",
            va="center",
            fontsize=8.8,
            color=color,
        )

    ax_effect.axvline(0, color=INK, linewidth=1.0, zorder=1)
    ax_effect.set_xlim(-15, 31)
    ax_effect.set_ylim(-0.55, 1.55)
    ax_effect.set_yticks(metric_y)
    ax_effect.set_yticklabels([row[0] for row in metric_rows], fontsize=9.4)
    ax_effect.set_xticks([-10, 0, 10, 20, 30])
    ax_effect.set_xlabel("effect vs matched control · pp for pass rate, % for steps", fontsize=8.8)
    ax_effect.set_title("Selfverify effect (95% CI)", loc="left", fontsize=11.0, fontweight=400, pad=12)
    style_axis(ax_effect, grid="x", keep=("bottom",))
    # Hairline separators keep the hero readable without card chrome.
    for x in (0.275, 0.565):
        fig.add_artist(Line2D([x, x], [0.18, 0.76], transform=fig.transFigure, color=LIGHT_GRAY, linewidth=0.8))

    add_source(
        fig,
        "Sources: docs/data/tb_baseline_summary.json · pooled paired selfverify comparison reported in EXPERIMENTS.md",
        x=0.055,
    )
    return save_figure(fig, slug)
