"""Shared visual system for HarnessForge report figures."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterable
from pathlib import Path

os.environ.setdefault(
    "MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "harnessforge-matplotlib")
)

import matplotlib as mpl

mpl.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure

ROOT = Path(__file__).parents[2]
DATA = ROOT / "docs" / "data"
FIGURES = ROOT / "docs" / "figures"
INDUSTRIAL = FIGURES / "industrial"

INK = "#1a1a2e"
TEAL = "#2a9d8f"
CORAL = "#e94560"
AMBER = "#e9c46a"
GRAY = "#8d99ae"
LIGHT_GRAY = "#d9dee8"
GRID = "#e4e7ed"
BG = "#f7f8fa"
WHITE = "#ffffff"


def configure_style() -> None:
    """Apply a sober, README-safe analytics style."""
    mpl.rcParams.update(
        {
            "figure.facecolor": BG,
            "savefig.facecolor": BG,
            "axes.facecolor": BG,
            "axes.edgecolor": LIGHT_GRAY,
            "axes.labelcolor": INK,
            "axes.titlecolor": INK,
            "axes.titlesize": 16,
            "axes.titleweight": 400,
            "axes.titlepad": 18,
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "text.color": INK,
            "xtick.color": INK,
            "ytick.color": INK,
            "grid.color": GRID,
            "grid.linewidth": 0.8,
            "grid.alpha": 0.8,
            "legend.frameon": False,
            "legend.labelcolor": INK,
            "lines.solid_capstyle": "round",
            "patch.edgecolor": "none",
            "svg.fonttype": "none",
            "svg.hashsalt": "harnessforge",
        }
    )


def style_axis(
    ax: Axes,
    *,
    grid: str | None = "y",
    zero_line: bool = False,
    keep: Iterable[str] = ("left", "bottom"),
) -> None:
    """Reduce chart chrome while retaining quantitative structure."""
    keep_set = set(keep)
    for name, spine in ax.spines.items():
        spine.set_visible(name in keep_set)
        spine.set_color(LIGHT_GRAY)
        spine.set_linewidth(0.8)
    ax.tick_params(length=0, pad=7)
    if grid:
        ax.grid(axis=grid, zorder=0)
    else:
        ax.grid(False)
    ax.set_axisbelow(True)
    if zero_line:
        ax.axhline(0, color=INK, linewidth=1.1, zorder=2)


def add_chart_title(
    fig: Figure,
    title: str,
    subtitle: str | None = None,
    *,
    x: float = 0.06,
    y: float = 0.955,
) -> None:
    """Add a consistent report title and optional evidence subtitle."""
    fig.text(x, y, title, color=INK, fontsize=18, fontweight=400, va="top")
    if subtitle:
        fig.text(x, y - 0.047, subtitle, color=GRAY, fontsize=9.5, va="top")


def add_source(fig: Figure, text: str, *, x: float = 0.06, y: float = 0.025) -> None:
    """Place compact provenance inside the figure boundary."""
    fig.text(x, y, text, color=GRAY, fontsize=7.5, va="bottom")


def direct_label(ax: Axes, x: float, y: float, text: str, *, color: str = INK, **kwargs) -> None:
    defaults = {"ha": "center", "va": "bottom", "fontsize": 9, "color": color}
    defaults.update(kwargs)
    ax.text(x, y, text, **defaults)


def pct(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}%}"


def pp(value: float, digits: int = 1, signed: bool = True) -> str:
    sign = "+" if signed and value > 0 else ""
    return f"{sign}{value * 100:.{digits}f} pp"


def save_figure(fig: Figure, slug: str, *, aliases: Iterable[str] = ()) -> list[Path]:
    """Write deterministic PNG and SVG masters plus optional legacy PNG aliases."""
    INDUSTRIAL.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    png = INDUSTRIAL / f"{slug}.png"
    svg = INDUSTRIAL / f"{slug}.svg"
    fig.savefig(
        png,
        dpi=180,
        bbox_inches="tight",
        pad_inches=0.16,
        metadata={"Software": "HarnessForge figure generator"},
    )
    fig.savefig(
        svg,
        bbox_inches="tight",
        pad_inches=0.16,
        metadata={"Date": None, "Creator": "HarnessForge figure generator"},
    )
    written.extend((png, svg))
    for alias in aliases:
        target = FIGURES / alias
        fig.savefig(
            target,
            dpi=180,
            bbox_inches="tight",
            pad_inches=0.16,
            metadata={"Software": "HarnessForge figure generator"},
        )
        written.append(target)
    plt.close(fig)
    return written
