"""Charts 6-10: controlled comparisons and efficiency."""

from __future__ import annotations

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.ticker import FuncFormatter, PercentFormatter

from .common import (
    AMBER,
    BG,
    CORAL,
    GRAY,
    INK,
    LIGHT_GRAY,
    TEAL,
    add_chart_title,
    add_source,
    save_figure,
    style_axis,
)
from .data import (
    SELFVERIFY_EFFECTS,
    VALIDATION_GROUPS,
    baseline,
    calibration,
    finishfix,
    selfverify,
    source_path,
)


def _label_bars(ax, bars, labels: list[str], *, offset: float, fontsize: float = 9) -> None:
    """Place deterministic value labels above a bar collection."""
    for bar, label in zip(bars, labels):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + offset,
            label,
            ha="center",
            va="bottom",
            color=INK,
            fontsize=fontsize,
            fontweight=400,
        )


def chart_finishfix_ab(slug: str):
    """Show the finish-fix trade-off in three unit-safe A/B facets."""
    fig = plt.figure(figsize=(12.4, 5.25), facecolor=BG)
    gs = fig.add_gridspec(1, 3, width_ratios=(1.0, 1.0, 1.22))
    ax_pass = fig.add_subplot(gs[0, 0])
    ax_cost = fig.add_subplot(gs[0, 1])
    ax_exit = fig.add_subplot(gs[0, 2])

    add_chart_title(
        fig,
        "Finish-Fix A/B: Cheaper, But Not Better",
        "Matched 10-task control and treatment cohorts · 20 scored runs per arm",
    )

    arms = ["Control", "Finish-fix"]
    arm_colors = [GRAY, CORAL]

    pass_values = [0.500, 0.400]
    pass_bars = ax_pass.bar(arms, pass_values, color=arm_colors, width=0.56, zorder=3)
    _label_bars(ax_pass, pass_bars, ["50.0%", "40.0%"], offset=0.018)
    ax_pass.set_ylim(0, 0.66)
    ax_pass.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    ax_pass.set_ylabel("Pass rate")
    ax_pass.set_title("Outcome quality", loc="left", fontsize=12, pad=12)
    ax_pass.text(
        0.5,
        0.615,
        "Δ −10.0 pp\n95% CI [−30.0, +10.0 pp]",
        ha="center",
        va="top",
        color=CORAL,
        fontsize=8.5,
        linespacing=1.35,
    )
    style_axis(ax_pass, grid="y")

    cost_values = [0.196, 0.158]
    cost_bars = ax_cost.bar(arms, cost_values, color=[GRAY, TEAL], width=0.56, zorder=3)
    _label_bars(ax_cost, cost_bars, ["$0.196", "$0.158"], offset=0.006)
    ax_cost.set_ylim(0, 0.25)
    ax_cost.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"${value:.2f}"))
    ax_cost.set_ylabel("Average API cost / run")
    ax_cost.set_title("Resource use", loc="left", fontsize=12, pad=12)
    ax_cost.annotate(
        "−19%",
        xy=(1, cost_values[1]),
        xytext=(1, 0.228),
        ha="center",
        va="center",
        color=TEAL,
        fontsize=10,
        fontweight=400,
        arrowprops={"arrowstyle": "-|>", "color": TEAL, "lw": 1.2},
    )
    style_axis(ax_cost, grid="y")

    finished = [0, 8]
    max_steps = [20, 12]
    y = [1, 0]
    ax_exit.barh(y, max_steps, color=CORAL, height=0.46, label="max_steps", zorder=3)
    ax_exit.barh(
        y,
        finished,
        left=max_steps,
        color=TEAL,
        height=0.46,
        label="finished_done",
        zorder=3,
    )
    ax_exit.set_yticks(y, arms)
    ax_exit.set_xlim(0, 20)
    ax_exit.set_xlabel("Runs (n=20 per arm)")
    ax_exit.set_title("Exit behavior", loc="left", fontsize=12, pad=12)
    ax_exit.text(10, 1, "20 max_steps", ha="center", va="center", color="white", fontsize=9)
    ax_exit.text(6, 0, "12 max_steps", ha="center", va="center", color="white", fontsize=9)
    ax_exit.text(16, 0, "8 finish", ha="center", va="center", color="white", fontsize=9)
    ax_exit.legend(
        handles=[Patch(color=CORAL, label="max_steps"), Patch(color=TEAL, label="finished_done")],
        loc="lower center",
        bbox_to_anchor=(0.5, -0.26),
        ncol=2,
        fontsize=8,
    )
    style_axis(ax_exit, grid="x", keep=("bottom",))

    fig.subplots_adjust(left=0.07, right=0.98, top=0.77, bottom=0.20, wspace=0.36)
    add_source(
        fig,
        f"Source: {source_path('tb_finishfix_summary.json')} and matched baseline slice; "
        "paired bootstrap CI from EXPERIMENTS.md",
    )
    return save_figure(fig, slug, aliases=("ab_finishfix.png",))


def _effect_row(
    ax,
    *,
    delta: float,
    lo: float | None,
    hi: float | None,
    color: str,
    title: str,
    value_label: str,
    status: str,
    xlim: tuple[float, float],
    formatter,
    xlabel: str,
) -> None:
    """Render one unit-specific forest row."""
    ax.axvline(0, color=INK, linewidth=1.0, zorder=1)
    if lo is not None and hi is not None:
        ax.plot([lo, hi], [0, 0], color=color, linewidth=3.0, zorder=3)
        ax.plot([lo, lo], [-0.08, 0.08], color=color, linewidth=1.5, zorder=3)
        ax.plot([hi, hi], [-0.08, 0.08], color=color, linewidth=1.5, zorder=3)
    ax.scatter([delta], [0], s=72, color=color, edgecolor=BG, linewidth=1.3, zorder=4)
    ax.set_xlim(*xlim)
    ax.set_ylim(-0.42, 0.42)
    ax.set_yticks([])
    ax.xaxis.set_major_formatter(FuncFormatter(formatter))
    ax.set_xlabel(xlabel, fontsize=8.5, color=GRAY)
    ax.set_title(title, loc="left", fontsize=11.5, pad=9)
    ax.text(
        1.0,
        0.82,
        value_label,
        transform=ax.transAxes,
        ha="right",
        va="center",
        fontsize=9,
        color=INK,
        fontweight=400,
    )
    ax.text(
        1.0,
        0.58,
        status,
        transform=ax.transAxes,
        ha="right",
        va="center",
        fontsize=8.3,
        color=color,
    )
    style_axis(ax, grid="x", keep=("bottom",))


def chart_selfverify_effects(slug: str):
    """Use separate axes so pass-rate, dollar, and relative effects retain units."""
    fig, axes = plt.subplots(3, 1, figsize=(10.6, 7.1), facecolor=BG)
    add_chart_title(
        fig,
        "Selfverify: Win Is On The High-Power Metric",
        "Paired bootstrap · 10 shared tasks · 3 repeats per arm (30 runs / arm)",
    )

    pass_effect = SELFVERIFY_EFFECTS["pass_rate"]
    _effect_row(
        axes[0],
        delta=pass_effect["delta"] * 100,
        lo=pass_effect["lo"] * 100,
        hi=pass_effect["hi"] * 100,
        color=GRAY,
        title="Pass rate",
        value_label="+6.7 pp   95% CI [−10.0, +26.7 pp]",
        status="CI crosses zero · not significant",
        xlim=(-13, 30),
        formatter=lambda value, _: f"{value:+.0f}",
        xlabel="Treatment − control (percentage points)",
    )

    cost_effect = SELFVERIFY_EFFECTS["cost_per_run"]
    _effect_row(
        axes[1],
        delta=cost_effect["delta"] * 100,
        lo=None,
        hi=None,
        color=GRAY,
        title="API cost / run",
        value_label="−1.3% · CI crosses zero · not significant",
        status="CI bounds not reported in the source summary",
        xlim=(-5, 5),
        formatter=lambda value, _: f"{value:+.0f}%",
        xlabel="Relative change vs control",
    )

    step_effect = SELFVERIFY_EFFECTS["steps_per_run"]
    _effect_row(
        axes[2],
        delta=step_effect["delta"] * 100,
        lo=step_effect["lo"] * 100,
        hi=step_effect["hi"] * 100,
        color=TEAL,
        title="Agent steps / run",
        value_label="−6.9%   95% CI [−13.3%, −1.6%]",
        status="CI excludes zero · significant",
        xlim=(-15, 4),
        formatter=lambda value, _: f"{value:+.0f}%",
        xlabel="Relative change vs control",
    )

    fig.subplots_adjust(left=0.10, right=0.96, top=0.79, bottom=0.11, hspace=0.78)
    add_source(
        fig,
        "Source: pooled tb_baseline + tb_base_extra vs selfverify runs; "
        "cost row uses the reported −1.3% and qualitative CI status",
    )
    return save_figure(fig, slug, aliases=("selfverify_metrics.png",))


def chart_high_signal_validation(slug: str):
    """Pair observed arm rates with effect strips for the selected validation groups."""
    fig = plt.figure(figsize=(12.4, 6.8), facecolor=BG)
    gs = fig.add_gridspec(2, 3, height_ratios=(2.8, 1.0))
    bar_axes = [fig.add_subplot(gs[0, idx]) for idx in range(3)]
    effect_axes = [fig.add_subplot(gs[1, idx]) for idx in range(3)]

    add_chart_title(
        fig,
        "High-Signal Validation Set",
        "Targets lean positive; the three regression guards remain flat · pooled 3 repeats / arm",
    )

    panel_titles = ["Targets (7)", "All selected tasks (10)", "Regression guards (3)"]
    for idx, (group, ax, effect_ax) in enumerate(zip(VALIDATION_GROUPS, bar_axes, effect_axes)):
        values = [group["control"], group["treatment"]]
        bars = ax.bar([0, 1], values, color=[GRAY, TEAL], width=0.54, zorder=3)
        _label_bars(ax, bars, [f"{value:.1%}" for value in values], offset=0.025)
        ax.set_xticks([0, 1], ["Control", "Selfverify"])
        ax.set_ylim(0, 1.05)
        ax.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
        if idx == 0:
            ax.set_ylabel("Pass rate")
        else:
            ax.set_yticklabels([])
        ax.set_title(panel_titles[idx], fontsize=12, pad=11)
        style_axis(ax, grid="y")

        effect_ax.axvline(0, color=INK, linewidth=1.0, zorder=1)
        delta_pp = group["delta"] * 100
        if group["lo"] is not None and group["hi"] is not None:
            lo_pp = group["lo"] * 100
            hi_pp = group["hi"] * 100
            effect_ax.plot([lo_pp, hi_pp], [0, 0], color=AMBER, linewidth=3, zorder=3)
            effect_ax.plot([lo_pp, lo_pp], [-0.09, 0.09], color=AMBER, linewidth=1.4)
            effect_ax.plot([hi_pp, hi_pp], [-0.09, 0.09], color=AMBER, linewidth=1.4)
            effect_ax.scatter([delta_pp], [0], s=62, color=TEAL, edgecolor=BG, zorder=4)
            effect_ax.text(
                0.5,
                0.82,
                f"Δ {delta_pp:+.1f} pp · CI [{lo_pp:+.1f}, {hi_pp:+.1f}]",
                transform=effect_ax.transAxes,
                ha="center",
                color=INK,
                fontsize=8.2,
            )
            effect_ax.text(
                0.5,
                0.63,
                "positive signal · still underpowered",
                transform=effect_ax.transAxes,
                ha="center",
                color=AMBER,
                fontsize=7.8,
            )
        else:
            effect_ax.scatter([0], [0], s=62, color=GRAY, edgecolor=BG, zorder=4)
            effect_ax.text(
                0.5,
                0.82,
                "Δ 0.0 pp · unchanged",
                transform=effect_ax.transAxes,
                ha="center",
                color=INK,
                fontsize=8.2,
            )
            effect_ax.text(
                0.5,
                0.63,
                "no guard CI reported",
                transform=effect_ax.transAxes,
                ha="center",
                color=GRAY,
                fontsize=7.8,
            )
        effect_ax.set_xlim(-13, 36)
        effect_ax.set_ylim(-0.34, 0.34)
        effect_ax.set_yticks([])
        effect_ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:+.0f}"))
        effect_ax.set_xlabel("Pass-rate effect (pp)", fontsize=8, color=GRAY)
        style_axis(effect_ax, grid="x", keep=("bottom",))

    fig.legend(
        handles=[Patch(color=GRAY, label="Control"), Patch(color=TEAL, label="Selfverify")],
        loc="upper center",
        bbox_to_anchor=(0.5, 0.80),
        ncol=2,
        fontsize=8.5,
    )
    fig.subplots_adjust(left=0.07, right=0.98, top=0.70, bottom=0.14, hspace=0.50, wspace=0.28)
    add_source(
        fig,
        "Source: 2+1 pooled runs; targets = 6 harness-fixable failures + vulnerable-secret; "
        "guards = 3 always-pass tasks",
    )
    return save_figure(fig, slug)


def chart_proposal_calibration(slug: str):
    """Compare pass-rate predictions to controlled observations, then isolate steps."""
    rows = calibration()
    labels = ["Native round 1", "TB finish-fix", "TB selfverify"]
    predictions = [row["predicted"] * 100 for row in rows]
    observations = [row["controlled"] * 100 for row in rows]
    observed_colors = [GRAY, CORAL, AMBER]

    fig = plt.figure(figsize=(12.2, 5.8), facecolor=BG)
    gs = fig.add_gridspec(1, 2, width_ratios=(1.8, 1.0))
    ax = fig.add_subplot(gs[0, 0])
    ax_steps = fig.add_subplot(gs[0, 1])
    add_chart_title(
        fig,
        "Predicted vs Observed Harness Effects",
        "Pass-rate calibration stays separate from the confirmed steps/run effect",
    )

    y = [2, 1, 0]
    ax.axvline(0, color=INK, linewidth=1.0, zorder=1)
    for idx, (yi, predicted, observed, color) in enumerate(
        zip(y, predictions, observations, observed_colors)
    ):
        ax.plot([observed, predicted], [yi, yi], color=LIGHT_GRAY, linewidth=5, zorder=2)
        ax.scatter(
            [predicted],
            [yi],
            s=80,
            marker="D",
            facecolor=BG,
            edgecolor=INK,
            linewidth=1.5,
            zorder=4,
        )
        ax.scatter([observed], [yi], s=88, color=color, edgecolor=BG, linewidth=1.2, zorder=5)
        ax.text(predicted, yi + 0.20, f"pred {predicted:+.0f}", ha="center", fontsize=8, color=INK)
        observed_label = "≈0" if idx == 0 else f"{observed:+.1f}"
        suffix = " targets" if idx == 2 else ""
        ax.text(
            observed,
            yi - 0.22,
            f"observed {observed_label}{suffix}",
            ha="center",
            fontsize=8,
            color=color,
        )

    ax.text(
        0.01,
        0.93,
        "Native small-sample gate: +100 pp\n(off-scale; did not hold up)",
        transform=ax.transAxes,
        ha="left",
        va="top",
        color=AMBER,
        fontsize=8.2,
    )
    ax.set_yticks(y, labels)
    ax.set_xlim(-14, 14)
    ax.set_ylim(-0.55, 2.55)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:+.0f}"))
    ax.set_xlabel("Predicted / controlled pass-rate effect (percentage points)")
    ax.set_title("Calibration dumbbell", loc="left", fontsize=12, pad=12)
    ax.legend(
        handles=[
            Line2D([0], [0], marker="D", markerfacecolor=BG, markeredgecolor=INK,
                   linestyle="none", label="Predicted"),
            Line2D([0], [0], marker="o", color=GRAY, linestyle="none", label="Controlled observed"),
        ],
        loc="lower left",
        fontsize=8,
        ncol=2,
    )
    style_axis(ax, grid="x", keep=("bottom",))

    ax_steps.axvline(0, color=INK, linewidth=1.0, zorder=1)
    ax_steps.plot([-13.3, -1.6], [0, 0], color=TEAL, linewidth=3.2, zorder=3)
    ax_steps.plot([-13.3, -13.3], [-0.08, 0.08], color=TEAL, linewidth=1.5)
    ax_steps.plot([-1.6, -1.6], [-0.08, 0.08], color=TEAL, linewidth=1.5)
    ax_steps.scatter([-6.9], [0], s=90, color=TEAL, edgecolor=BG, linewidth=1.2, zorder=4)
    ax_steps.set_xlim(-15, 4)
    ax_steps.set_ylim(-0.5, 0.5)
    ax_steps.set_yticks([0], ["TB selfverify"])
    ax_steps.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:+.0f}%"))
    ax_steps.set_xlabel("Relative steps/run change")
    ax_steps.set_title("Confirmed efficiency effect", loc="left", fontsize=12, pad=12)
    ax_steps.text(
        0.5,
        0.76,
        "−6.9%\n95% CI [−13.3%, −1.6%]\nCI excludes zero",
        transform=ax_steps.transAxes,
        ha="center",
        va="center",
        color=TEAL,
        fontsize=9,
        linespacing=1.35,
        fontweight=400,
    )
    style_axis(ax_steps, grid="x", keep=("bottom",))

    fig.subplots_adjust(left=0.13, right=0.98, top=0.76, bottom=0.16, wspace=0.31)
    add_source(fig, f"Source: {source_path('calibration.json')}; steps CI from pooled eval/compare.py")
    return save_figure(fig, slug)


def chart_efficiency_under_constraint(slug: str):
    """Describe three run cohorts without presenting them as a causal comparison."""
    base = baseline()
    fix = finishfix()
    verify = selfverify()
    cohorts = [base, fix, verify]
    labels = [
        "Baseline\n20 tasks · 40 runs",
        "Finish-fix\n10 tasks · 20 runs",
        "Selfverify\n10 tasks · 20 runs",
    ]
    colors = [GRAY, CORAL, TEAL]

    metrics = [
        (
            "Pass rate",
            [cohort["pass_rate"] for cohort in cohorts],
            "share of scored runs",
            lambda value: f"{value:.1%}",
            (0, 0.58),
        ),
        (
            "API cost / run",
            [cohort["total_cost_usd"] / cohort["n_scored"] for cohort in cohorts],
            "USD per scored run",
            lambda value: f"${value:.3f}",
            (0, 0.31),
        ),
        (
            "Step-budget pressure",
            [cohort["exit_reasons"].get("max_steps", 0) / cohort["n_scored"] for cohort in cohorts],
            "share ending at max_steps",
            lambda value: f"{value:.0%}",
            (0, 1.05),
        ),
        (
            "Natural finish behavior",
            [cohort["exit_reasons"].get("finished_done", 0) / cohort["n_scored"] for cohort in cohorts],
            "share ending finished_done",
            lambda value: f"{value:.1%}",
            (0, 0.50),
        ),
    ]

    fig, axes = plt.subplots(2, 2, figsize=(12.2, 7.4), facecolor=BG)
    add_chart_title(
        fig,
        "Efficiency Under Constraint",
        "Descriptive cohort snapshots — task mixes differ; use the matched A/B charts for causal claims",
    )

    for ax, (title, values, ylabel, formatter, ylim) in zip(axes.flat, metrics):
        bars = ax.bar(range(3), values, color=colors, width=0.58, zorder=3)
        offset = (ylim[1] - ylim[0]) * 0.025
        _label_bars(ax, bars, [formatter(value) for value in values], offset=offset, fontsize=8.5)
        ax.set_xticks(range(3), labels)
        ax.set_ylim(*ylim)
        ax.set_ylabel(ylabel, fontsize=8.5)
        ax.set_title(title, loc="left", fontsize=12, pad=10)
        if title == "API cost / run":
            ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"${value:.2f}"))
        else:
            ax.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
        style_axis(ax, grid="y")

    fig.text(
        0.5,
        0.075,
        "Matched pooled evidence · selfverify steps/run −6.9%  ·  95% CI [−13.3%, −1.6%]  ·  significant",
        ha="center",
        va="center",
        color=TEAL,
        fontsize=10,
        fontweight=400,
    )
    fig.subplots_adjust(left=0.08, right=0.98, top=0.78, bottom=0.15, hspace=0.48, wspace=0.27)
    add_source(
        fig,
        "Source: tb_baseline_summary.json, tb_finishfix_summary.json, tb_selfverify_summary.json; "
        "pooled steps evidence from eval/compare.py",
    )
    return save_figure(fig, slug)
