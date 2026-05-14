"""Build summary figures for the historical probe series.

Reads metrics.json from each notes_cli probe-run and summary.json
from each legacy/ tag, plots evolution across 11 versions.

Output: docs/article/probe-runs/figures/*.svg
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import Patch

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "docs" / "article" / "probe-runs"
FIGS = RUNS / "figures"
FIGS.mkdir(parents=True, exist_ok=True)

# Run-id → tag mapping (by SHA prefix in folder name)
RUN_BY_TAG: dict[str, str] = {
    "v0.3.0": "notes_cli-notes_cli_empty-9d9ba4f-20260513-181458",
    "v0.4.0": "notes_cli-notes_cli_empty-5f09a0d-20260513-182920",
    "v0.5.0": "notes_cli-notes_cli_empty-a91c68d-20260513-183830",
    "v0.6.0": "notes_cli-notes_cli_empty-767e02b-20260513-184838",
    "v0.7.0": "notes_cli-notes_cli_empty-c0fcb6e-20260513-185759",
    "v0.8.0": "notes_cli-notes_cli_empty-d6e9c37-20260513-192850",
    "v0.9.0": "notes_cli-notes_cli_empty-a10a21a-20260513-194448",
    "v0.10.0": "notes_cli-notes_cli_empty-fcef19f-20260513-195644",
    "v0.11.0": "notes_cli-notes_cli_empty-1a7c385-20260513-200643",
    "v0.12.0": "notes_cli-notes_cli_empty-7569eaf-20260513-201718",
    "main": "notes_cli-notes_cli_empty-a0c416c-20260513-202813",
}

TAGS = list(RUN_BY_TAG.keys())
TAG_LABELS = [t.replace("v0.", "0.").replace(".0", "") if t != "main" else "main" for t in TAGS]

# Reached level for live probe per tag.
# 1.0 = L1, 2.0 = L2, 3.0 = L3, 3.5 = L3+, 4.0 = L4, ...
LEVELS = {
    "v0.3.0": 3.0,
    "v0.4.0": 3.0,
    "v0.5.0": 3.0,
    "v0.6.0": 3.0,
    "v0.7.0": 3.0,
    "v0.8.0": 3.5,
    "v0.9.0": 3.5,
    "v0.10.0": 3.0,
    "v0.11.0": 3.0,
    "v0.12.0": 3.0,
    "main": 3.0,
}

# Palette
COL_LIVE = "#1f77b4"
COL_PROBE = "#2ca02c"
COL_CODE = "#9467bd"
COL_RECIPES = "#ff7f0e"
COL_FORKS = "#e377c2"
COL_FORK_REV = "#bcbd22"
COL_E2E = "#17becf"
COL_REGRESS = "#d62728"
COL_GREY = "#7f7f7f"


def load_metrics() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for tag, run_id in RUN_BY_TAG.items():
        m = json.loads((RUNS / run_id / "metrics.json").read_text())
        out[tag] = m
    return out


def load_legacy() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for tag in TAGS:
        leg_tag = "main" if tag == "main" else tag
        path = RUNS / "legacy" / leg_tag / "summary.json"
        s = json.loads(path.read_text())
        per_probe: dict[str, tuple[int, int] | None | str] = {}
        for p in s["probes"]:
            name = p["name"]
            if p["status"] == "skipped":
                per_probe[name] = None
            elif p["status"] == "non_zero_exit":
                per_probe[name] = "FAIL"
            else:
                pr = p.get("pass_rate_guess")
                per_probe[name] = tuple(pr) if pr else "ok"
        out[tag] = per_probe
    return out


def style_axes(ax):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", linestyle=":", linewidth=0.6, alpha=0.7)
    ax.set_axisbelow(True)


def fig_reached_level(metrics: dict[str, dict]) -> None:
    fig, ax = plt.subplots(figsize=(10, 4.5))
    xs = list(range(len(TAGS)))
    ys = [LEVELS[t] for t in TAGS]

    # Color bands for eras
    ax.axvspan(-0.4, 4.4, color="#f0f0f0", alpha=0.5)  # baseline v0.3-v0.7
    ax.axvspan(4.4, 6.4, color="#e8f4e8", alpha=0.7)  # watershed v0.8-v0.9
    ax.axvspan(6.4, 10.4, color="#fbeaea", alpha=0.6)  # regress v0.10-main

    ax.plot(xs, ys, marker="o", markersize=10, linewidth=2.2, color=COL_LIVE)

    # Annotations on data points
    for x, y, _tag in zip(xs, ys, TAGS, strict=True):
        label = "L3+" if y == 3.5 else "L3"
        ax.annotate(
            label,
            (x, y),
            textcoords="offset points",
            xytext=(0, 12),
            ha="center",
            fontsize=9,
            fontweight="bold" if y == 3.5 else "normal",
            color="#2a7a2a" if y == 3.5 else "#444",
        )

    ax.set_xticks(xs)
    ax.set_xticklabels(TAGS, rotation=30, ha="right")
    ax.set_yticks([2.5, 3.0, 3.5, 4.0])
    ax.set_yticklabels(["—", "L3", "L3+", "L4"])
    ax.set_ylim(2.6, 4.2)
    ax.set_ylabel("reached level (live notes_cli)")
    ax.set_title("Live probe reached_level по 11 версиям", fontsize=12, fontweight="bold", pad=14)

    # Era legend
    legend_elems = [
        Patch(facecolor="#f0f0f0", alpha=0.7, label="baseline (v0.3-v0.7)"),
        Patch(facecolor="#e8f4e8", alpha=0.9, label="watershed (v0.8-v0.9)"),
        Patch(facecolor="#fbeaea", alpha=0.8, label="регресс (v0.10-main)"),
    ]
    ax.legend(handles=legend_elems, loc="lower right", frameon=False, fontsize=9)

    style_axes(ax)
    plt.tight_layout()
    out = FIGS / "01_reached_level.svg"
    plt.savefig(out, format="svg", bbox_inches="tight")
    plt.savefig(out.with_suffix(".png"), format="png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"wrote {out.name}")


def fig_live_activity(metrics: dict[str, dict]) -> None:
    """Two-panel: write_file count + wall_sec."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.5))
    xs = list(range(len(TAGS)))
    wf = [metrics[t]["tool_calls_by_name"].get("write_file", 0) for t in TAGS]
    wall = [metrics[t]["wall_time_sec"] for t in TAGS]

    # write_file bars
    colors_wf = [COL_PROBE if v > 0 else COL_GREY for v in wf]
    bars1 = ax1.bar(xs, wf, color=colors_wf, edgecolor="white", linewidth=1)
    for b, v in zip(bars1, wf, strict=True):
        if v > 0:
            ax1.annotate(
                str(v),
                (b.get_x() + b.get_width() / 2, v),
                ha="center",
                va="bottom",
                fontsize=9,
                fontweight="bold",
            )
    ax1.set_xticks(xs)
    ax1.set_xticklabels(TAGS, rotation=30, ha="right", fontsize=9)
    ax1.set_ylabel("write_file calls")
    ax1.set_title("write_file calls per live run", fontsize=11, fontweight="bold")
    style_axes(ax1)

    # wall_sec bars
    bars2 = ax2.bar(xs, wall, color=COL_LIVE, edgecolor="white", linewidth=1, alpha=0.85)
    for b, v in zip(bars2, wall, strict=True):
        ax2.annotate(
            f"{int(v)}s", (b.get_x() + b.get_width() / 2, v), ha="center", va="bottom", fontsize=8
        )
    ax2.set_xticks(xs)
    ax2.set_xticklabels(TAGS, rotation=30, ha="right", fontsize=9)
    ax2.set_ylabel("wall time, sec")
    ax2.set_title("wall time per live run", fontsize=11, fontweight="bold")
    style_axes(ax2)

    plt.tight_layout()
    out = FIGS / "02_live_activity.svg"
    plt.savefig(out, format="svg", bbox_inches="tight")
    plt.savefig(out.with_suffix(".png"), format="png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"wrote {out.name}")


def fig_tokens(metrics: dict[str, dict]) -> None:
    fig, ax = plt.subplots(figsize=(10, 4.5))
    xs = list(range(len(TAGS)))
    total = [metrics[t]["prompt_tokens_total"] / 1000 for t in TAGS]
    peak = [metrics[t]["prompt_tokens_peak"] / 1000 for t in TAGS]
    requests = [metrics[t]["agent_llm_requests"] for t in TAGS]

    w = 0.4
    ax.bar(
        [x - w / 2 for x in xs],
        total,
        width=w,
        color=COL_LIVE,
        label="prompt_tokens_total (kT, sum)",
    )
    ax.bar(
        [x + w / 2 for x in xs],
        peak,
        width=w,
        color=COL_RECIPES,
        label="prompt_tokens_peak (kT, single req)",
    )
    ax2 = ax.twinx()
    ax2.plot(xs, requests, marker="D", linewidth=1.5, color=COL_REGRESS, label="agent_llm_requests")
    ax2.set_ylabel("LLM requests", color=COL_REGRESS)
    ax2.tick_params(axis="y", labelcolor=COL_REGRESS)
    ax2.spines["top"].set_visible(False)
    ax2.set_ylim(0, max(requests) * 1.25)

    ax.set_xticks(xs)
    ax.set_xticklabels(TAGS, rotation=30, ha="right")
    ax.set_ylabel("tokens, kT")
    ax.set_title(
        "Стоимость live-прогона: total / peak / requests", fontsize=12, fontweight="bold", pad=14
    )
    style_axes(ax)

    lines1, labels1 = ax.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(lines1 + lines2, labels1 + labels2, loc="upper left", frameon=False, fontsize=9)

    plt.tight_layout()
    out = FIGS / "03_tokens.svg"
    plt.savefig(out, format="svg", bbox_inches="tight")
    plt.savefig(out.with_suffix(".png"), format="png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"wrote {out.name}")


def fig_legacy_probes(legacy: dict[str, dict]) -> None:
    fig, ax = plt.subplots(figsize=(11, 5))
    xs = list(range(len(TAGS)))

    series = [
        ("probe.py", "max 9", COL_PROBE, "o", "-"),
        ("probe_recipes.py", "max 3", COL_RECIPES, "s", "-"),
        ("probe_forks.py", "max 4", COL_FORKS, "^", "-"),
        ("probe_fork_reviewer.py", "max 3", COL_FORK_REV, "D", "-"),
    ]

    # We'll plot each probe as % of its max so they all live on one [0,100]% axis
    for probe, _max_label, color, marker, ls in series:
        ys = []
        for tag in TAGS:
            v = legacy[tag].get(probe)
            if v is None:
                ys.append(None)
            elif v == "FAIL":
                ys.append(0)
            elif isinstance(v, tuple):
                a, b = v
                ys.append(100 * a / b)
            else:
                ys.append(None)
        xs_clean = [x for x, y in zip(xs, ys, strict=True) if y is not None]
        ys_clean = [y for y in ys if y is not None]
        ax.plot(
            xs_clean,
            ys_clean,
            marker=marker,
            linewidth=1.8,
            markersize=8,
            color=color,
            linestyle=ls,
            label=probe,
        )

    # FAIL markers for e2e_forks v0.12
    e2e_xs, e2e_ys = [], []
    for x, tag in zip(xs, TAGS, strict=True):
        v = legacy[tag].get("probe_e2e_forks.py")
        if v == "FAIL":
            e2e_xs.append(x)
            e2e_ys.append(0)
        elif v == "ok":
            e2e_xs.append(x)
            e2e_ys.append(50)  # show as "partial" since we only know "ok / FAIL"
    if e2e_xs:
        ax.scatter(
            e2e_xs,
            e2e_ys,
            color=COL_E2E,
            marker="x",
            s=120,
            linewidths=2.5,
            label="probe_e2e_forks (×=FAIL, dot=ok)",
        )

    # Highlight regress eras
    ax.axvspan(6.4, 10.4, color="#fbeaea", alpha=0.4, zorder=0)

    ax.set_xticks(xs)
    ax.set_xticklabels(TAGS, rotation=30, ha="right")
    ax.set_ylim(-5, 110)
    ax.set_yticks([0, 25, 50, 75, 100])
    ax.set_yticklabels(["0%", "25%", "50%", "75%", "100%"])
    ax.set_ylabel("pass rate")
    ax.set_title("Legacy probe pack — эволюция по версиям", fontsize=12, fontweight="bold", pad=14)
    ax.legend(loc="lower left", frameon=False, fontsize=9, ncol=2)
    style_axes(ax)

    plt.tight_layout()
    out = FIGS / "04_legacy_probes.svg"
    plt.savefig(out, format="svg", bbox_inches="tight")
    plt.savefig(out.with_suffix(".png"), format="png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"wrote {out.name}")


def fig_tool_calls_breakdown(metrics: dict[str, dict]) -> None:
    fig, ax = plt.subplots(figsize=(11, 5))
    xs = list(range(len(TAGS)))

    tool_kinds = [
        ("write_file", COL_PROBE),
        ("shell_exec", COL_RECIPES),
        ("annotate_plan", COL_FORKS),
        ("project_map", COL_FORK_REV),
        ("read_file", COL_E2E),
        ("auto_load_skill", COL_GREY),
        ("load_skill", "#cccccc"),
    ]
    bottoms = [0] * len(TAGS)
    for kind, col in tool_kinds:
        vals = [metrics[t]["tool_calls_by_name"].get(kind, 0) for t in TAGS]
        ax.bar(xs, vals, bottom=bottoms, color=col, edgecolor="white", linewidth=0.5, label=kind)
        bottoms = [b + v for b, v in zip(bottoms, vals, strict=True)]

    # Total tool_calls annotation on top
    for x, total in zip(xs, bottoms, strict=True):
        if total > 0:
            ax.annotate(
                str(total), (x, total), ha="center", va="bottom", fontsize=9, fontweight="bold"
            )

    ax.set_xticks(xs)
    ax.set_xticklabels(TAGS, rotation=30, ha="right")
    ax.set_ylabel("tool_calls per live run")
    ax.set_title("Tool calls breakdown per live run", fontsize=12, fontweight="bold", pad=14)
    ax.legend(loc="upper left", frameon=False, fontsize=8, ncol=2)
    style_axes(ax)

    plt.tight_layout()
    out = FIGS / "05_tool_calls_breakdown.svg"
    plt.savefig(out, format="svg", bbox_inches="tight")
    plt.savefig(out.with_suffix(".png"), format="png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"wrote {out.name}")


def main() -> None:
    metrics = load_metrics()
    legacy = load_legacy()
    fig_reached_level(metrics)
    fig_live_activity(metrics)
    fig_tokens(metrics)
    fig_legacy_probes(legacy)
    fig_tool_calls_breakdown(metrics)


if __name__ == "__main__":
    main()
