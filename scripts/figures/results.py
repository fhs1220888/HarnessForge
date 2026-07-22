"""Charts 1-5: benchmark results and intervention arc."""

from __future__ import annotations

import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.patches import FancyBboxPatch, Rectangle
from matplotlib.ticker import PercentFormatter

from .common import (
    AMBER,
    BG,
    CORAL,
    GRAY,
    INK,
    LIGHT_GRAY,
    TEAL,
    WHITE,
    add_chart_title,
    add_source,
    pct,
    save_figure,
    style_axis,
)
from .data import (
    SELFVERIFY_EFFECTS,
    TB_CAPABILITY_LIMITED,
    TB_HARNESS_FIXABLE,
    baseline,
    calibration,
    load_json,
    source_path,
)


def _signed(value: float, digits: int = 2) -> str:
    """Format a signed decimal effect without changing its unit."""
    if value > 0:
        return f"+{value:.{digits}f}"
    return f"{value:.{digits}f}"


def _kpi_card(
    ax: Axes,
    *,
    label: str,
    value: str,
    detail: str,
    accent: str,
) -> None:
    """Draw one restrained KPI card in axes coordinates."""
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    panel = FancyBboxPatch(
        (0.01, 0.02),
        0.98,
        0.96,
        boxstyle="round,pad=0.012,rounding_size=0.025",
        transform=ax.transAxes,
        facecolor=WHITE,
        edgecolor=LIGHT_GRAY,
        linewidth=0.8,
    )
    ax.add_patch(panel)
    ax.plot(
        [0.06, 0.94],
        [0.91, 0.91],
        color=accent,
        linewidth=3.0,
        solid_capstyle="round",
        transform=ax.transAxes,
    )
    ax.text(
        0.07,
        0.76,
        label.upper(),
        transform=ax.transAxes,
        color=GRAY,
        fontsize=8.2,
        fontweight=400,
        va="top",
    )
    ax.text(
        0.07,
        0.56,
        value,
        transform=ax.transAxes,
        color=INK,
        fontsize=23,
        fontweight=400,
        va="top",
    )
    ax.text(
        0.07,
        0.18,
        detail,
        transform=ax.transAxes,
        color=INK,
        fontsize=9.2,
        va="bottom",
    )


def chart_terminal_bench_baseline(slug: str):
    """Render the baseline KPIs and exact run termination distribution."""
    summary = baseline()
    n_scored = int(summary["n_scored"])
    passed = sum(sum(bool(outcome) for outcome in outcomes) for outcomes in summary["per_task"].values())
    exits = summary["exit_reasons"]
    max_steps = int(exits.get("max_steps", 0))
    finished = int(exits.get("finished_done", 0))
    max_tokens = int(exits.get("max_tokens", 0))
    infra_error = int(summary.get("n_infra_error", 0))

    fig = plt.figure(figsize=(11.6, 5.4))
    grid = fig.add_gridspec(
        2,
        4,
        left=0.06,
        right=0.97,
        bottom=0.16,
        top=0.78,
        height_ratios=(1.0, 1.12),
        hspace=0.48,
        wspace=0.18,
    )
    add_chart_title(
        fig,
        "Terminal-Bench Baseline",
        "Real external-benchmark results · step-budget exhaustion dominates termination behavior",
    )

    cards = (
        (
            "Pass rate",
            pct(float(summary["pass_rate"]), 1),
            f"{passed} / {n_scored} scored runs",
            TEAL,
        ),
        (
            "Total API cost",
            f"${float(summary['total_cost_usd']):.2f}",
            f"across {n_scored} scored runs",
            AMBER,
        ),
        (
            "Budget exits",
            f"{max_steps} / {n_scored}",
            f"max_steps · {pct(max_steps / n_scored, 0)}",
            CORAL,
        ),
        (
            "Evaluation set",
            f"{int(summary['n_tasks'])} × {int(summary['repeats'])}",
            "tasks × repeats",
            GRAY,
        ),
    )
    for index, (label, value, detail, accent) in enumerate(cards):
        _kpi_card(
            fig.add_subplot(grid[0, index]),
            label=label,
            value=value,
            detail=detail,
            accent=accent,
        )

    ax = fig.add_subplot(grid[1, :])
    left = 0
    segments = (
        ("max_steps", max_steps, CORAL),
        ("finished_done", finished, TEAL),
        ("max_tokens", max_tokens, AMBER),
    )
    centers: dict[str, float] = {}
    for label, count, color in segments:
        if count:
            ax.barh(0, count, left=left, height=0.38, color=color, zorder=3)
            centers[label] = left + count / 2
            left += count

    ax.text(
        centers["max_steps"],
        0,
        f"max_steps   {max_steps} · {pct(max_steps / n_scored, 0)}",
        ha="center",
        va="center",
        color=INK,
        fontsize=10.5,
        fontweight=400,
    )
    ax.annotate(
        f"finished_done\n{finished} · {pct(finished / n_scored, 1)}",
        xy=(centers["finished_done"], 0.19),
        xytext=(centers["finished_done"] - 1.8, 0.57),
        ha="center",
        va="bottom",
        fontsize=8.6,
        color=INK,
        arrowprops={"arrowstyle": "-", "color": TEAL, "linewidth": 1.0},
    )
    ax.annotate(
        f"max_tokens\n{max_tokens} · {pct(max_tokens / n_scored, 1)}",
        xy=(centers["max_tokens"], -0.19),
        xytext=(centers["max_tokens"] - 1.2, -0.53),
        ha="center",
        va="top",
        fontsize=8.6,
        color=INK,
        arrowprops={"arrowstyle": "-", "color": AMBER, "linewidth": 1.0},
    )
    ax.set_xlim(0, n_scored)
    ax.set_ylim(-0.72, 0.78)
    ax.set_xticks(range(0, n_scored + 1, 10))
    ax.set_yticks([])
    ax.set_xlabel(f"runs (n={n_scored})", labelpad=8)
    style_axis(ax, grid="x", keep=("bottom",))
    add_source(
        fig,
        f"Source: {source_path('tb_baseline_summary.json')} · infra_error: {infra_error}",
    )
    return save_figure(fig, slug, aliases=("tb_baseline.png",))


def chart_per_task_pass_rate(slug: str):
    """Render a stable ranked task view with explicit zero-rate marks."""
    summary = baseline()
    rows = []
    for order, (name, outcomes) in enumerate(summary["per_task"].items()):
        rate = sum(bool(outcome) for outcome in outcomes) / len(outcomes)
        rows.append((name, rate, order))
    rows.sort(key=lambda row: (-row[1], row[2]))

    names = [row[0] for row in rows]
    rates = [row[1] for row in rows]
    y_positions = list(range(len(rows)))
    colors = [TEAL if rate >= 0.75 else CORAL if rate <= 0.25 else AMBER for rate in rates]

    fig = plt.figure(figsize=(11.8, 8.0))
    grid = fig.add_gridspec(
        1,
        2,
        left=0.27,
        right=0.97,
        bottom=0.11,
        top=0.84,
        width_ratios=(4.7, 1.55),
        wspace=0.04,
    )
    add_chart_title(
        fig,
        "Per-Task Pass Rate — Terminal-Bench Subset",
        "Two repeats per task · color thresholds: ≥75% strong, 25–75% borderline, ≤25% failed",
    )

    ax = fig.add_subplot(grid[0, 0])
    tag_ax = fig.add_subplot(grid[0, 1], sharey=ax)
    ax.barh(y_positions, [1.0] * len(rows), height=0.58, color=GRAY, alpha=0.12, zorder=1)
    ax.barh(y_positions, rates, height=0.58, color=colors, zorder=3)

    for y, rate, color in zip(y_positions, rates, colors):
        if rate == 0:
            ax.scatter(0.008, y, s=28, marker="o", color=color, zorder=4)
            ax.text(0.025, y, "0%", ha="left", va="center", color=INK, fontsize=8.5)
        elif rate >= 0.96:
            ax.text(
                0.98,
                y,
                pct(rate, 0),
                ha="right",
                va="center",
                color=INK,
                fontsize=8.5,
                fontweight=400,
            )
        else:
            ax.text(
                rate + 0.015,
                y,
                pct(rate, 0),
                ha="left",
                va="center",
                color=INK,
                fontsize=8.5,
                fontweight=400,
            )

    ax.set_xlim(0, 1.04)
    ax.set_ylim(len(rows) - 0.45, -0.55)
    ax.set_yticks(y_positions, labels=names)
    ax.set_xticks((0, 0.25, 0.50, 0.75, 1.00))
    ax.xaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    ax.set_xlabel("pass rate · two repeats", labelpad=8)
    ax.tick_params(axis="y", labelsize=9.2)
    style_axis(ax, grid="x", keep=("bottom",))

    tag_ax.set_xlim(0, 1)
    tag_ax.set_ylim(len(rows) - 0.45, -0.55)
    tag_ax.axis("off")
    tag_ax.set_title("FAILURE CLASS", loc="left", color=GRAY, fontsize=8.5, pad=8)
    for y, name in zip(y_positions, names):
        if name in TB_HARNESS_FIXABLE:
            label = "harness-fixable"
            face = AMBER
        elif name in TB_CAPABILITY_LIMITED:
            label = "capability-limited"
            face = CORAL
        else:
            continue
        tag_ax.text(
            0.03,
            y,
            label,
            ha="left",
            va="center",
            color=INK,
            fontsize=7.8,
            bbox={
                "boxstyle": "round,pad=0.28",
                "facecolor": face,
                "edgecolor": face,
                "linewidth": 0.7,
                "alpha": 0.16,
            },
        )

    add_source(fig, f"Source: {source_path('tb_baseline_summary.json')}")
    return save_figure(fig, slug)


def chart_exit_reason_breakdown(slug: str):
    """Show why runs ended without assigning visible width to zero counts."""
    summary = baseline()
    exits = summary["exit_reasons"]
    n_scored = int(summary["n_scored"])
    max_steps = int(exits.get("max_steps", 0))
    finished = int(exits.get("finished_done", 0))
    max_tokens = int(exits.get("max_tokens", 0))
    infra_error = int(summary.get("n_infra_error", 0))

    fig, ax = plt.subplots(figsize=(9.8, 3.6))
    fig.subplots_adjust(left=0.075, right=0.96, bottom=0.25, top=0.66)
    add_chart_title(fig, "Why Runs Ended", y=0.97)
    fig.text(
        0.06,
        0.845,
        "Most runs exhausted the step budget instead of finishing naturally",
        color=GRAY,
        fontsize=9.5,
        va="top",
    )

    segments = (
        ("max_steps", max_steps, CORAL),
        ("finished_done", finished, TEAL),
        ("max_tokens", max_tokens, AMBER),
    )
    left = 0
    centers: dict[str, float] = {}
    for label, count, color in segments:
        if count:
            ax.barh(0, count, left=left, height=0.36, color=color, zorder=3)
            centers[label] = left + count / 2
            left += count

    ax.text(
        centers["max_steps"],
        0,
        f"max_steps   {max_steps} runs · {pct(max_steps / n_scored, 0)}",
        ha="center",
        va="center",
        color=INK,
        fontsize=10.5,
        fontweight=400,
    )
    ax.annotate(
        f"finished_done\n{finished} · {pct(finished / n_scored, 1)}",
        xy=(centers["finished_done"], 0.18),
        xytext=(centers["finished_done"] - 2.0, 0.56),
        ha="center",
        va="bottom",
        color=INK,
        fontsize=8.8,
        arrowprops={"arrowstyle": "-", "color": TEAL, "linewidth": 1.0},
    )
    ax.annotate(
        f"max_tokens\n{max_tokens} · {pct(max_tokens / n_scored, 1)}",
        xy=(centers["max_tokens"], -0.18),
        xytext=(centers["max_tokens"] - 1.2, -0.52),
        ha="center",
        va="top",
        color=INK,
        fontsize=8.8,
        arrowprops={"arrowstyle": "-", "color": AMBER, "linewidth": 1.0},
    )
    ax.set_xlim(0, n_scored)
    ax.set_ylim(-0.67, 0.70)
    ax.set_xticks(range(0, n_scored + 1, 10))
    ax.set_yticks([])
    ax.set_xlabel(f"runs (n={n_scored})", labelpad=8)
    style_axis(ax, grid="x", keep=("bottom",))
    add_source(
        fig,
        f"Source: {source_path('tb_baseline_summary.json')} · infra_error: {infra_error}",
    )
    return save_figure(fig, slug)


def chart_native_headroom(slug: str):
    """Compare saturated native baselines with the same suite under a tight budget."""
    tight_budget = load_json("native_baseline_v4_summary.json")
    rates = (1.0, 1.0, float(tight_budget["pass_rate"]))
    x_positions = (0.0, 1.45, 2.27)
    labels = (
        "10 tasks\n30 steps",
        "18 tasks\n30 steps",
        f"{int(tight_budget['n_tasks'])} tasks\n8 steps",
    )

    fig, ax = plt.subplots(figsize=(8.8, 4.8))
    fig.subplots_adjust(left=0.10, right=0.96, bottom=0.20, top=0.72)
    add_chart_title(
        fig,
        "Headroom Comes From Budget, Not Task Difficulty",
        "The controlled contrast is the same 18-task suite at 30 versus 8 steps",
    )

    bars = ax.bar(
        x_positions,
        rates,
        width=0.60,
        color=(GRAY, TEAL, CORAL),
        edgecolor=(GRAY, TEAL, AMBER),
        linewidth=(0.0, 0.0, 1.8),
        zorder=3,
    )
    bars[2].set_hatch("///")
    ax.axhline(1.0, color=GRAY, linestyle=(0, (4, 3)), linewidth=1.1, zorder=2)

    for bar, rate in zip(bars, rates):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            rate + 0.025,
            pct(rate, 1 if rate < 1 else 0),
            ha="center",
            va="bottom",
            color=INK,
            fontsize=10.5,
            fontweight=400,
        )

    same_suite_left = x_positions[1]
    same_suite_right = x_positions[2]
    ax.plot(
        [same_suite_left, same_suite_left, same_suite_right, same_suite_right],
        [1.085, 1.115, 1.115, 1.085],
        color=INK,
        linewidth=0.9,
        clip_on=False,
    )
    ax.text(
        (same_suite_left + same_suite_right) / 2,
        1.13,
        "same 18-task suite",
        ha="center",
        va="bottom",
        color=INK,
        fontsize=8.5,
        fontweight=400,
    )
    controlled_delta = rates[2] - rates[1]
    ax.text(
        x_positions[2],
        rates[2] * 0.54,
        f"{controlled_delta * 100:.1f} pp\nwith 8-step cap",
        ha="center",
        va="center",
        color=INK,
        fontsize=9.0,
        fontweight=400,
    )

    ax.set_xlim(-0.55, 2.82)
    ax.set_ylim(0, 1.19)
    ax.set_xticks(x_positions, labels=labels)
    ax.set_yticks((0, 0.25, 0.50, 0.75, 1.00))
    ax.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    ax.set_ylabel("pass rate")
    style_axis(ax, grid="y")
    add_source(
        fig,
        "Source: EXPERIMENTS.md · "
        f"{source_path('native_baseline_v4_summary.json')}",
    )
    return save_figure(fig, slug, aliases=("native_headroom.png",))


def _intervention_card(
    ax: Axes,
    *,
    x: float,
    width: float,
    accent: str,
    title: str,
    hypothesis: str,
    predicted: str,
    observed: tuple[tuple[str, str], ...],
    decision: str,
    decision_note: str,
) -> None:
    """Draw a timeline card with aligned evidence fields."""
    y = 0.075
    height = 0.68
    panel = FancyBboxPatch(
        (x, y),
        width,
        height,
        boxstyle="round,pad=0.012,rounding_size=0.016",
        transform=ax.transAxes,
        facecolor=WHITE,
        edgecolor=LIGHT_GRAY,
        linewidth=0.9,
    )
    ax.add_patch(panel)
    ax.add_patch(
        Rectangle(
            (x, y + height - 0.012),
            width,
            0.012,
            transform=ax.transAxes,
            facecolor=accent,
            edgecolor="none",
        )
    )
    left = x + 0.025
    ax.text(
        left,
        y + height - 0.055,
        title,
        transform=ax.transAxes,
        color=INK,
        fontsize=11.2,
        fontweight=400,
        va="top",
    )
    ax.text(
        left,
        y + height - 0.105,
        hypothesis,
        transform=ax.transAxes,
        color=GRAY,
        fontsize=8.5,
        va="top",
    )
    ax.text(
        left,
        y + height - 0.175,
        "PREDICTED",
        transform=ax.transAxes,
        color=GRAY,
        fontsize=7.5,
        fontweight=400,
        va="top",
    )
    ax.text(
        left,
        y + height - 0.214,
        predicted,
        transform=ax.transAxes,
        color=INK,
        fontsize=9.2,
        fontweight=400,
        va="top",
    )
    ax.text(
        left,
        y + height - 0.280,
        "OBSERVED",
        transform=ax.transAxes,
        color=GRAY,
        fontsize=7.5,
        fontweight=400,
        va="top",
    )
    row_y = y + height - 0.320
    for text, color in observed:
        ax.scatter(
            [left + 0.006],
            [row_y - 0.010],
            s=18,
            color=color,
            transform=ax.transAxes,
            zorder=4,
        )
        ax.text(
            left + 0.020,
            row_y,
            text,
            transform=ax.transAxes,
            color=INK,
            fontsize=8.35,
            va="top",
        )
        row_y -= 0.052

    decision_y = y + 0.075
    ax.text(
        left,
        decision_y + 0.067,
        "DECISION",
        transform=ax.transAxes,
        color=GRAY,
        fontsize=7.5,
        fontweight=400,
        va="top",
    )
    ax.text(
        left,
        decision_y + 0.024,
        decision,
        transform=ax.transAxes,
        color=INK,
        fontsize=8.5,
        fontweight=400,
        va="top",
        bbox={
            "boxstyle": "round,pad=0.28",
            "facecolor": accent,
            "edgecolor": accent,
            "linewidth": 0.8,
            "alpha": 0.16,
        },
    )
    ax.text(
        left,
        y + 0.035,
        decision_note,
        transform=ax.transAxes,
        color=INK,
        fontsize=7.9,
        va="bottom",
    )


def chart_intervention_arc(slug: str):
    """Render proposal predictions, controlled evidence, and merge decisions."""
    rows = {row["round"]: row for row in calibration()}
    native = rows["native round 1"]
    finishfix = rows["TB finish-fix"]
    selfverify = rows["TB selfverify"]
    effects = SELFVERIFY_EFFECTS["steps_per_run"]

    fig, ax = plt.subplots(figsize=(12.4, 6.0))
    fig.subplots_adjust(left=0.04, right=0.97, bottom=0.08, top=0.83)
    add_chart_title(
        fig,
        "Harness Intervention Arc",
        "Prediction → controlled evidence → decision · the confirmed win moved to efficiency",
        x=0.04,
    )
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    card_x = (0.015, 0.348, 0.681)
    card_width = 0.304
    centers = [x + card_width / 2 for x in card_x]
    timeline_y = 0.865
    ax.plot(
        [centers[0], centers[-1]],
        [timeline_y, timeline_y],
        color=LIGHT_GRAY,
        linewidth=1.2,
        transform=ax.transAxes,
        zorder=1,
    )
    for index, center in enumerate(centers, start=1):
        ax.scatter(
            [center],
            [timeline_y],
            s=260,
            facecolor=BG,
            edgecolor=INK,
            linewidth=1.0,
            transform=ax.transAxes,
            zorder=3,
        )
        ax.text(
            center,
            timeline_y,
            str(index),
            transform=ax.transAxes,
            ha="center",
            va="center",
            color=INK,
            fontsize=9,
            fontweight=400,
            zorder=4,
        )

    _intervention_card(
        ax,
        x=card_x[0],
        width=card_width,
        accent=CORAL,
        title="Native round 1",
        hypothesis="reverify after patch",
        predicted=f"Pass-rate Δ {_signed(float(native['predicted']))}",
        observed=(
            (f"Small-sample Δ {_signed(float(native['smallval']))}", AMBER),
            (f"Controlled A/B ≈ {float(native['controlled']):.2f}", CORAL),
        ),
        decision="REJECTED",
        decision_note="Validation signal did not reproduce.",
    )
    _intervention_card(
        ax,
        x=card_x[1],
        width=card_width,
        accent=CORAL,
        title="TB finish-fix",
        hypothesis="finish when done",
        predicted=f"Pass-rate Δ {_signed(float(finishfix['predicted']))}",
        observed=(
            (f"Pass-rate Δ {_signed(float(finishfix['controlled']))}", CORAL),
            ("Cost/run −19%", TEAL),
        ),
        decision="REJECTED",
        decision_note="Cheaper, but completion was premature.",
    )
    _intervention_card(
        ax,
        x=card_x[2],
        width=card_width,
        accent=AMBER,
        title="TB selfverify",
        hypothesis="verify deliverables",
        predicted=f"Pass-rate Δ {_signed(float(selfverify['predicted']))}",
        observed=(
            (f"Targets Δ {_signed(float(selfverify['controlled']), 3)}", AMBER),
            ("All tasks Δ +0.067", AMBER),
            ("Steps/run −6.9%", TEAL),
            (
                f"95% CI [{float(effects['lo']) * 100:.1f}%, "
                f"{float(effects['hi']) * 100:.1f}%]",
                TEAL,
            ),
        ),
        decision="BEST EVIDENCE · NOT MERGED",
        decision_note="Efficiency CI excludes zero; pass rate is underpowered.",
    )

    add_source(
        fig,
        f"Source: {source_path('calibration.json')} · EXPERIMENTS.md",
        x=0.04,
    )
    return save_figure(fig, slug)
