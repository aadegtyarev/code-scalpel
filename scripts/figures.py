"""Article figures generator.

Reads bench data hardcoded inline (single-source-of-truth lives in
docs/bench-models.md; we mirror the numbers here to keep the
figures reproducible without a parser). On change to the .md,
update the BENCH list below and re-run:

    python scripts/figures.py

Output: docs/article/figures/*.svg. Vector format keeps weight
low and scales for Habr. PNG fallbacks only if SVG turns out to
misrender somewhere downstream.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt


@dataclass(frozen=True)
class BenchRow:
    name: str
    pass_count: int
    total: int
    seconds: int
    short: str  # axis label
    family: str  # grouping for colour

    @property
    def pass_rate(self) -> float:
        return self.pass_count / self.total * 100


# Mirrors docs/bench-models.md as of 2026-05-13.
BENCH: list[BenchRow] = [
    BenchRow("google/gemma-4-26b-a4b", 24, 24, 120, "gemma-4-26b\n(4B active)", "gemma"),
    BenchRow("qwen2.5-coder-14b", 23, 24, 45, "qwen2.5-coder-14b", "qwen-coder"),
    BenchRow("openai/gpt-oss-20b", 21, 24, 106, "gpt-oss-20b", "gpt-oss"),
    BenchRow("qwen3.5-9b", 19, 24, 73, "qwen3.5-9b", "qwen-dense"),
    BenchRow("qwen3.6-35b-a3b", 13, 24, 542, "qwen3.6-35b\n(3B active)", "qwen-moe"),
    BenchRow("qwen2.5-coder-7b", 13, 24, 42, "qwen2.5-coder-7b", "qwen-coder"),
    BenchRow("qwen3.5-35b-a3b", 10, 24, 303, "qwen3.5-35b\n(3B active)", "qwen-moe"),
    BenchRow("meta-llama-3.1-8b", 9, 24, 415, "llama-3.1-8b", "llama"),
]


FAMILY_COLOURS = {
    "gemma": "#1f77b4",
    "qwen-coder": "#ff7f0e",
    "gpt-oss": "#2ca02c",
    "qwen-dense": "#d62728",
    "qwen-moe": "#9467bd",
    "llama": "#8c564b",
}


def _ensure_outdir() -> Path:
    out = Path("docs/article/figures")
    out.mkdir(parents=True, exist_ok=True)
    return out


def fig_pass_rate_bar(out: Path) -> Path:
    """Bar chart of pass-rate across 8 models. Sorted descending by
    rate; bars coloured by model family so qwen-coder-14b and qwen-
    coder-7b read as one group (the family our default lives in)."""
    rows = sorted(BENCH, key=lambda r: r.pass_rate, reverse=True)
    fig, ax = plt.subplots(figsize=(10, 5.5))
    bars = ax.bar(
        [r.short for r in rows],
        [r.pass_rate for r in rows],
        color=[FAMILY_COLOURS[r.family] for r in rows],
        edgecolor="#333",
        linewidth=0.5,
    )
    for bar, row in zip(bars, rows, strict=True):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 1.5,
            f"{row.pass_count}/{row.total}\n({row.pass_rate:.0f}%)",
            ha="center",
            va="bottom",
            fontsize=9,
        )
    ax.set_ylim(0, 110)
    ax.set_ylabel("Pass rate, %")
    ax.set_title("Patch-suite pass rate — 8 моделей, 24 теста")
    ax.set_axisbelow(True)
    ax.grid(axis="y", alpha=0.3)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.xticks(rotation=20, ha="right")
    plt.tight_layout()
    path = out / "fig01_pass_rate_bar.svg"
    fig.savefig(path)
    plt.close(fig)
    return path


def fig_latency_vs_quality(out: Path) -> Path:
    """Scatter: time-to-finish vs pass rate. Pareto-frontier
    annotation calls out coder-14b (cheapest right-edge model)
    and gemma-4-26b-a4b (only 100%). Long-tail models in the
    bottom-right are visually obvious dominated points."""
    fig, ax = plt.subplots(figsize=(10, 6))
    for row in BENCH:
        ax.scatter(
            row.seconds,
            row.pass_rate,
            s=160,
            color=FAMILY_COLOURS[row.family],
            edgecolor="#333",
            linewidth=0.6,
            zorder=3,
        )
        offset_x, offset_y = 8, 1.4
        if row.name == "qwen2.5-coder-7b":  # crowded with coder-14b on the y-axis
            offset_x, offset_y = 8, -3.5
        ax.annotate(
            row.short.replace("\n", " "),
            (row.seconds, row.pass_rate),
            xytext=(offset_x, offset_y),
            textcoords="offset points",
            fontsize=9,
        )
    # Pareto annotation
    ax.annotate(
        "Pareto-оптимум:\nдефолт scalpel",
        xy=(45, 96),
        xytext=(140, 70),
        fontsize=9,
        ha="left",
        arrowprops={"arrowstyle": "->", "color": "#555", "lw": 1.2},
        bbox={"boxstyle": "round,pad=0.4", "facecolor": "#fff7e0", "edgecolor": "#c08000"},
    )
    ax.set_xlabel("Время на полный бенч (24 теста), сек")
    ax.set_ylabel("Pass rate, %")
    ax.set_title("Latency vs quality — почему coder-14b остался дефолтом")
    ax.set_ylim(0, 110)
    ax.set_xlim(0, 600)
    ax.set_axisbelow(True)
    ax.grid(alpha=0.3)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.tight_layout()
    path = out / "fig02_latency_vs_quality.svg"
    fig.savefig(path)
    plt.close(fig)
    return path


def fig_three_way_compare(out: Path) -> Path:
    """Habr-friendly infographic: gemma vs qwen-coder-14b vs gpt-oss.
    Two grouped bars per model: pass-rate (left) and time (right,
    on a secondary scale). Three columns only — the «show me the
    three serious candidates» summary."""
    names = ["gemma-4-26b\n(4B active)", "qwen2.5-coder-14b", "gpt-oss-20b"]
    pass_rates = [100.0, 96.0, 87.5]
    seconds = [120, 45, 106]

    fig, ax_left = plt.subplots(figsize=(9, 5.5))
    width = 0.35
    x_positions = range(len(names))
    x_left = [i - width / 2 for i in x_positions]
    x_right = [i + width / 2 for i in x_positions]
    bars_pass = ax_left.bar(
        x_left,
        pass_rates,
        width=width,
        color="#1f77b4",
        edgecolor="#333",
        linewidth=0.5,
        label="Pass rate, %",
    )
    ax_left.set_ylabel("Pass rate, %", color="#1f77b4")
    ax_left.tick_params(axis="y", labelcolor="#1f77b4")
    ax_left.set_ylim(0, 115)
    ax_left.set_axisbelow(True)
    ax_left.grid(axis="y", alpha=0.25)
    ax_left.spines["top"].set_visible(False)
    for bar, value in zip(bars_pass, pass_rates, strict=True):
        ax_left.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 1.5,
            f"{value:.0f}%",
            ha="center",
            va="bottom",
            fontsize=9,
            color="#1f77b4",
        )

    ax_right = ax_left.twinx()
    bars_time = ax_right.bar(
        x_right,
        seconds,
        width=width,
        color="#ff7f0e",
        edgecolor="#333",
        linewidth=0.5,
        label="Bench duration, s",
    )
    ax_right.set_ylabel("Время полного бенча, сек", color="#ff7f0e")
    ax_right.tick_params(axis="y", labelcolor="#ff7f0e")
    ax_right.set_ylim(0, max(seconds) * 1.25)
    ax_right.spines["top"].set_visible(False)
    for bar, value in zip(bars_time, seconds, strict=True):
        ax_right.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + max(seconds) * 0.02,
            f"{value}s",
            ha="center",
            va="bottom",
            fontsize=9,
            color="#ff7f0e",
        )

    ax_left.set_xticks(list(x_positions))
    ax_left.set_xticklabels(names)
    ax_left.set_title("gemma vs qwen-coder vs gpt-oss — три серьёзных кандидата")
    plt.tight_layout()
    path = out / "fig03_three_way_compare.svg"
    fig.savefig(path)
    plt.close(fig)
    return path


def fig_patch_format_evolution(out: Path) -> Path:
    """Pass-rate evolution as the patch-exchange format changed.

    The four data points span three different bench sizes (15 →
    16 → 24) because the suite grew alongside the agent. We label
    raw counts above each bar so readers see the absolute numbers
    and the % to keep them comparable across denominators."""
    stages = [
        ("unified diff\n(raw)", 12, 15, "v0.1", "#d62728"),
        ("unified diff\n+ fuzzy applier", 13, 15, "v0.1.x", "#ff9896"),
        ("SEARCH/REPLACE\n+ text tool calls", 16, 16, "v0.2", "#1f77b4"),
        ("SEARCH/REPLACE\n+ native fn calls", 23, 24, "v0.3+", "#2ca02c"),
    ]
    fig, ax = plt.subplots(figsize=(9, 5))
    xs = list(range(len(stages)))
    rates = [p / t * 100 for _, p, t, _, _ in stages]
    bars = ax.bar(
        xs,
        rates,
        color=[c for _, _, _, _, c in stages],
        edgecolor="#333",
        linewidth=0.5,
    )
    for bar, (_, p, t, ver, _) in zip(bars, stages, strict=True):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 2,
            f"{p}/{t}\n{p / t * 100:.0f}%",
            ha="center",
            va="bottom",
            fontsize=9,
        )
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            -8,
            ver,
            ha="center",
            va="top",
            fontsize=8,
            color="#666",
        )
    ax.set_xticks(xs)
    ax.set_xticklabels([name for name, _, _, _, _ in stages])
    ax.set_ylim(0, 115)
    ax.set_ylabel("Pass rate, %")
    ax.set_title("Pass rate vs формат patch'а — модель та же, формат менялся")
    ax.set_axisbelow(True)
    ax.grid(axis="y", alpha=0.3)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.tight_layout()
    path = out / "fig04_patch_format_evolution.svg"
    fig.savefig(path)
    plt.close(fig)
    return path


def fig_token_budget_lazy_context(out: Path) -> Path:
    """Tokens-per-turn before/after lazy context. The «before» bar
    shows the range we actually saw (5–8k) as an errorbar; the
    «after» bar is the ~200 we measured on a casual greeting."""
    labels = [
        "До: eager stuff\n(весь project map\n+ первые файлы)",
        "После: lazy context\n(overview + tool calls\nпо требованию)",
    ]
    means = [6500, 200]
    yerr = [[1500, 0], [0, 0]]
    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.bar(
        labels,
        means,
        color=["#d62728", "#2ca02c"],
        yerr=yerr,
        capsize=6,
        edgecolor="#333",
        linewidth=0.5,
    )
    for bar, value, err_pair in zip(bars, means, yerr, strict=True):
        label = f"~{value}\n(5000–8000)" if err_pair[0] else f"~{value}"
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 300,
            label,
            ha="center",
            va="bottom",
            fontsize=10,
        )
    ax.annotate(
        "≈×35\nменьше",
        xy=(1, 200),
        xytext=(0.5, 4200),
        ha="center",
        fontsize=11,
        color="#2ca02c",
        fontweight="bold",
        arrowprops={
            "arrowstyle": "->",
            "color": "#2ca02c",
            "lw": 1.4,
            "connectionstyle": "arc3,rad=-0.25",
        },
    )
    ax.set_ylabel("Токены на casual «привет»")
    ax.set_title("Контекстный бюджет — до и после lazy context")
    ax.set_ylim(0, 9500)
    ax.set_axisbelow(True)
    ax.grid(axis="y", alpha=0.3)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.tight_layout()
    path = out / "fig05_token_budget_lazy_context.svg"
    fig.savefig(path)
    plt.close(fig)
    return path


def main() -> None:
    out = _ensure_outdir()
    paths = [
        # Real bench data from docs/bench-models.md.
        fig_pass_rate_bar(out),
        fig_latency_vs_quality(out),
        fig_three_way_compare(out),
        # WIP — synthetic reconstructions from numbers in v1_devlog.md.
        # When the series goes to press, we'll re-shoot these from real
        # measurements at tags v0.1 / v0.2 / current — see
        # docs/article/README.md «archaeology pass». Functions stay
        # here as scaffolding.
        # fig_patch_format_evolution(out),
        # fig_token_budget_lazy_context(out),
    ]
    for p in paths:
        print(f"wrote {p}")


if __name__ == "__main__":
    main()
