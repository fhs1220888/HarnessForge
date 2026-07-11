"""Generate result figures for the README from runs/ data.

Reads committed summary/results JSON snapshots under docs/data/ (so figures are
reproducible without rerunning evals) and writes PNGs to docs/figures/.

Usage:
    python scripts/make_figures.py
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).parents[1]
DATA = ROOT / "docs" / "data"
FIG = ROOT / "docs" / "figures"
FIG.mkdir(parents=True, exist_ok=True)

INK = "#1a1a2e"
ACCENT = "#e94560"
MUTED = "#8d99ae"
GOOD = "#2a9d8f"


def _style(ax):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.tick_params(colors=INK)
    ax.yaxis.label.set_color(INK)
    ax.xaxis.label.set_color(INK)
    ax.title.set_color(INK)


def fig_native_headroom():
    """Pass rate across native-suite baselines: the 'headroom via budget' story."""
    labels = ["10 tasks\n30 steps", "18 tasks\n30 steps", "18 tasks\n8 steps"]
    rates = [1.00, 1.00, 0.667]
    fig, ax = plt.subplots(figsize=(6, 3.4))
    bars = ax.bar(labels, rates, color=[MUTED, MUTED, ACCENT], width=0.6)
    ax.axhline(1.0, ls="--", lw=1, color=MUTED)
    ax.set_ylim(0, 1.08)
    ax.set_ylabel("pass rate")
    ax.set_title("Headroom comes from budget, not task difficulty")
    for b, r in zip(bars, rates):
        ax.text(b.get_x() + b.get_width() / 2, r + 0.02, f"{r:.0%}",
                ha="center", color=INK, fontweight="bold")
    _style(ax)
    fig.tight_layout()
    fig.savefig(FIG / "native_headroom.png", dpi=150)
    plt.close(fig)


def fig_tb_baseline():
    """TB per-task pass rate + the max_steps finding."""
    s = json.loads((DATA / "tb_baseline_summary.json").read_text())
    per = s["per_task"]
    items = sorted(per.items(), key=lambda kv: -sum(kv[1]) / len(kv[1]))
    names = [k for k, _ in items]
    rates = [sum(v) / len(v) for _, v in items]
    colors = [GOOD if r >= 0.75 else ACCENT if r <= 0.25 else "#e9c46a" for r in rates]

    fig, ax = plt.subplots(figsize=(7, 5.2))
    ax.barh(names[::-1], rates[::-1], color=colors[::-1])
    ax.set_xlim(0, 1.05)
    ax.set_xlabel("pass rate (2 repeats)")
    ax.set_title(f"Terminal-Bench subset — baseline {s['pass_rate']:.1%}  "
                 f"({s['exit_reasons'].get('max_steps',0)}/{s['n_scored']} hit max_steps)")
    _style(ax)
    fig.tight_layout()
    fig.savefig(FIG / "tb_baseline.png", dpi=150)
    plt.close(fig)


def fig_ab_finishfix():
    """The A/B: efficiency gain, no pass-rate gain."""
    metrics = ["pass rate", "avg cost/run\n(normalized)"]
    control = [0.500, 1.00]
    treat = [0.400, 0.81]
    x = range(len(metrics))
    w = 0.36
    fig, ax = plt.subplots(figsize=(6, 3.6))
    ax.bar([i - w / 2 for i in x], control, width=w, label="control", color=MUTED)
    ax.bar([i + w / 2 for i in x], treat, width=w, label="finish-fix", color=ACCENT)
    ax.set_xticks(list(x))
    ax.set_xticklabels(metrics)
    ax.set_ylim(0, 1.15)
    ax.set_title("finish-fix A/B: −19% cost, no pass-rate gain")
    ax.legend(frameon=False)
    # annotate CI on pass rate
    ax.text(0, 0.55, "Δ −0.10\nCI [−0.30,+0.10]", ha="center", fontsize=8, color=INK)
    _style(ax)
    fig.tight_layout()
    fig.savefig(FIG / "ab_finishfix.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    fig_native_headroom()
    fig_tb_baseline()
    fig_ab_finishfix()
    print("wrote figures to", FIG)
