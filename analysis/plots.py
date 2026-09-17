"""
analysis/plots.py -- Reusable visualization functions

This module contains only functions -- each function returns a matplotlib
Figure, which the caller (analysis/compare.py, analysis/sweep_analysis.py)
saves to a file. This keeps the plotting logic in one place, and it can
also be reused from other scripts (e.g. run_demo.py, step 11).

Functions generating the four required figures according to chapter 7.1
of the documentation:
    find_critical_period()   -- helper function for figure 1 (finds the
                                 worst 7-day period in the baseline)
    plot_critical_period()   -- figure 1: critical period time series
    plot_comparison_table()  -- figure 2: comparison table
    plot_optimization_heatmap() -- figure 3: optimization heatmap
    plot_robustness_curve()  -- figure 4: robustness curve
"""

import sys
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

METRIC_LABELS = {
    "coldstart_count": ("Cold start count", "count/year", "less_is_better"),
    "lost_production_hours": ("Lost production time", "hours/year", "less_is_better"),
    "methane_output_kwh": ("Methane output", "kWh/year", "more_is_better"),
    "bess_deep_discharge": ("BESS deep discharges", "count/year", "less_is_better"),
    "curtailed_kwh": ("Curtailed PV energy", "kWh/year", "less_is_better"),
    "reactor_warm_fraction_pct": ("Reactor warm uptime", "%", "more_is_better"),
    "reserve_active_hours": ("Life insurance active time", "hours/year", "info_only"),
}


def find_critical_period(baseline_df: pd.DataFrame, window_days: int = 7):
    """
    Finds the window_days-long window in the baseline simulation during
    which the reactor spent the most hours in the cold or cold_start
    state -- this becomes the "critical period" for figure 1.

    Returns: (start_timestamp, end_timestamp)
    """
    window_hours = window_days * 24
    is_cold = baseline_df["reactor_state"].isin(["cold", "cold_start"]).astype(int)
    rolling_cold_hours = is_cold.rolling(window_hours).sum()

    end_ts = rolling_cold_hours.idxmax()
    end_pos = baseline_df.index.get_loc(end_ts)
    start_pos = max(0, end_pos - window_hours + 1)

    return baseline_df.index[start_pos], baseline_df.index[end_pos]


def plot_critical_period(
    baseline_df: pd.DataFrame,
    smart_df: pd.DataFrame,
    start,
    end,
    location_name: str = "",
) -> plt.Figure:
    """
    Required figure 1: critical period time series.
        Top panel:    PV production + BESS state of charge (baseline vs. proactive)
        Middle panel: Reactor temperature (baseline vs. proactive)
        Bottom panel: Life insurance mode active/inactive (proactive)
    """
    b = baseline_df.loc[start:end]
    s = smart_df.loc[start:end]

    fig, axes = plt.subplots(3, 1, figsize=(13, 9), sharex=True)

    # --- Top panel: PV + BESS SOC ---
    ax0 = axes[0]
    ax0.fill_between(b.index, b["pv_power_kw"], color="#fbbf24", alpha=0.4, label="PV production [kW]")
    ax0.set_ylabel("PV [kW]")
    ax0b = ax0.twinx()
    ax0b.plot(b.index, b["bess_soc_fraction"] * 100, color="#dc2626", linewidth=1.3, label="BESS SOC -- baseline")
    ax0b.plot(s.index, s["bess_soc_fraction"] * 100, color="#16a34a", linewidth=1.3, label="BESS SOC -- proactive")
    ax0b.set_ylabel("BESS SOC [%]")
    ax0b.set_ylim(0, 100)
    lines0, labels0 = ax0.get_legend_handles_labels()
    lines0b, labels0b = ax0b.get_legend_handles_labels()
    ax0.legend(lines0 + lines0b, labels0 + labels0b, loc="upper right", fontsize=9)
    ax0.set_title(f"Critical period -- {location_name} ({start:%Y-%m-%d} -- {end:%Y-%m-%d})")
    ax0.grid(alpha=0.3)

    # --- Middle panel: reactor temperature ---
    ax1 = axes[1]
    ax1.plot(b.index, b["reactor_temperature_c"], color="#dc2626", linewidth=1.3, label="Baseline (naive)")
    ax1.plot(s.index, s["reactor_temperature_c"], color="#16a34a", linewidth=1.3, label="Proactive (life insurance)")
    ax1.axhline(config.SABATIER_MIN_TEMP_C, color="#78716c", linestyle="--", linewidth=1, label="min_temp")
    ax1.set_ylabel("Reactor temp. [°C]")
    ax1.legend(loc="lower right", fontsize=9)
    ax1.grid(alpha=0.3)

    # --- Bottom panel: life insurance active/inactive ---
    ax2 = axes[2]
    ax2.fill_between(
        s.index, 0, s["reserve_active"].astype(int), step="post", color="#2563eb", alpha=0.5,
        label="Life insurance active",
    )
    ax2.set_ylim(-0.1, 1.1)
    ax2.set_yticks([0, 1])
    ax2.set_yticklabels(["inactive", "active"])
    ax2.set_xlabel("Time")
    ax2.legend(loc="upper right", fontsize=9)
    ax2.grid(alpha=0.3)

    fig.tight_layout()
    return fig


def plot_comparison_table(baseline_metrics: dict, smart_metrics: dict) -> plt.Figure:
    """Required figure 2: comparison table, with % improvement for every metric."""
    rows = []
    cell_colors = []
    for key, (label, unit, direction) in METRIC_LABELS.items():
        b_val = baseline_metrics[key]
        s_val = smart_metrics[key]

        if direction == "less_is_better" and b_val:
            improvement = (1 - s_val / b_val) * 100
        elif direction == "more_is_better" and b_val:
            improvement = (s_val / b_val - 1) * 100
        else:
            improvement = None

        improvement_str = f"{improvement:+.0f}%" if improvement is not None else "--"
        rows.append([label, unit, f"{b_val:,.0f}", f"{s_val:,.0f}", improvement_str])

        if improvement is None:
            cell_colors.append(["white"] * 5)
        else:
            good = improvement > 0
            color = "#dcfce7" if good else "#fee2e2"
            cell_colors.append(["white", "white", "white", "white", color])

    fig, ax = plt.subplots(figsize=(9, 0.5 * len(rows) + 0.8))
    ax.axis("off")

    table = ax.table(
        cellText=rows,
        colLabels=["Metric", "Unit", "Baseline", "Proactive", "Improvement"],
        cellColours=cell_colors,
        cellLoc="center",
        loc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1, 1.8)
    for col in range(5):
        table[0, col].set_facecolor("#1e293b")
        table[0, col].set_text_props(color="white", weight="bold")

    ax.set_title("Baseline vs. proactive controller -- annual metrics", fontsize=13, weight="bold", pad=12)
    fig.tight_layout()
    return fig


def plot_optimization_heatmap(sweep_df: pd.DataFrame, location: str, forecast_error_std: float = 0.0) -> plt.Figure:
    """
    Required figure 3: optimization heatmap for a single location.
        X axis: threshold_hours, Y axis: reserve_fraction
        Color: coldstart_count (the darker, the better -- viridis
               color scale, where the dark end corresponds to low values)
    """
    subset = sweep_df[(sweep_df["location"] == location) & (sweep_df["forecast_error_std"] == forecast_error_std)]
    pivot = subset.pivot(index="reserve_fraction", columns="threshold_hours", values="coldstart_count")
    pivot = pivot.sort_index(ascending=True).sort_index(axis=1, ascending=True)

    fig, ax = plt.subplots(figsize=(7, 5.5))
    im = ax.imshow(pivot.values, cmap="viridis", aspect="auto", origin="lower")

    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels(pivot.columns)
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels([f"{v:.2f}" for v in pivot.index])
    ax.set_xlabel("threshold_hours [hours]")
    ax.set_ylabel("reserve_fraction [fraction of BESS capacity]")

    location_name = config.LOCATIONS[location]["name"]
    ax.set_title(f"Optimization heatmap -- {location_name}\n(coldstart_count, with perfect forecast)")

    # Write the value into each cell -- for easier readability.
    for i in range(pivot.shape[0]):
        for j in range(pivot.shape[1]):
            value = pivot.values[i, j]
            text_color = "white" if value > np.nanmax(pivot.values) * 0.6 else "black"
            ax.text(j, i, f"{value:.0f}", ha="center", va="center", color=text_color, fontsize=9)

    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label("coldstart_count [count/year] -- fewer = better")

    fig.tight_layout()
    return fig


def plot_robustness_curve(sweep_df: pd.DataFrame, locations: list, reserve_fraction: float = None) -> plt.Figure:
    """
    Required figure 4: robustness curve.
        X axis: forecast_error_std, Y axis: coldstart_count
        Multiple lines: different threshold_hours values
        One panel per location -- shows which threshold is the most
        robust to inaccurate forecasts, and how this changes across
        locations.
    """
    reserve_fraction = config.RESERVE_FRACTION if reserve_fraction is None else reserve_fraction

    fig, axes = plt.subplots(1, len(locations), figsize=(5.5 * len(locations), 4.5), sharey=True)
    if len(locations) == 1:
        axes = [axes]

    threshold_values = sorted(sweep_df["threshold_hours"].unique())
    colors = plt.cm.plasma(np.linspace(0.1, 0.85, len(threshold_values)))

    for ax, location in zip(axes, locations):
        subset = sweep_df[(sweep_df["location"] == location) & (sweep_df["reserve_fraction"] == reserve_fraction)]
        for threshold_hours, color in zip(threshold_values, colors):
            line = subset[subset["threshold_hours"] == threshold_hours].sort_values("forecast_error_std")
            ax.plot(
                line["forecast_error_std"],
                line["coldstart_count"],
                marker="o",
                color=color,
                label=f"threshold={threshold_hours}h",
            )
        ax.set_title(config.LOCATIONS[location]["name"])
        ax.set_xlabel("forecast_error_std [fraction of PV capacity]")
        ax.grid(alpha=0.3)

    axes[0].set_ylabel("coldstart_count [count/year]")
    axes[-1].legend(loc="upper left", fontsize=8)
    fig.suptitle(f"Robustness to inaccurate forecasts (reserve_fraction = {reserve_fraction:.2f})")
    fig.tight_layout()
    return fig
