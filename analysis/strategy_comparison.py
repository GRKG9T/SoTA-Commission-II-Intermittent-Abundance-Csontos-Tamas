"""
analysis/strategy_comparison.py -- Analysis and visualization of the
7-strategy comparison

Produces the 4 requested figures:
    1. Main figure -- strategy comparison per location (bar chart)
    2. Robustness figure -- coldstart_count vs. forecast_error, 7 lines (Edinburgh)
    3. Complexity vs. effectiveness -- coldstart_count vs. complexity (Edinburgh)
    4. Critical period time series -- all 7 strategies at once (Sevilla + Edinburgh)

Usage:
    python analysis/strategy_comparison.py
"""

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
from analysis.plots import find_critical_period
from control.strategies import ALL_STRATEGIES
from simulation.strategy_sweep import simulate_with_strategy

# A unified color palette for all 7 strategies, the same on every figure --
# from simple (light) to complex (dark), so it stays easy to recognize
# which strategy is which across figures.
STRATEGY_COLORS = {
    "reactive_baseline": "#94a3b8",
    "fixed_reserve": "#60a5fa",
    "forecast_binary": "#34d399",
    "proportional_reserve": "#fbbf24",
    "temperature_based": "#f97316",
    "precharge": "#ef4444",
    "rolling_horizon": "#7c3aed",
}


def plot_strategy_comparison_bars(sweep_df: pd.DataFrame, locations: list) -> plt.Figure:
    """Figure 1 (main figure): 3 bar charts (per location), x=7 strategies, y=coldstart_count."""
    subset_all = sweep_df[sweep_df["forecast_error_std"] == 0.0]
    strategy_order = [s.name for s in ALL_STRATEGIES]
    display_names = [s.display_name for s in ALL_STRATEGIES]

    fig, axes = plt.subplots(1, len(locations), figsize=(5.5 * len(locations), 5.5), sharey=False)
    if len(locations) == 1:
        axes = [axes]

    for ax, location in zip(axes, locations):
        subset = subset_all[subset_all["location"] == location].set_index("strategy")
        values = [subset.loc[name, "coldstart_count"] if name in subset.index else np.nan for name in strategy_order]
        colors = [STRATEGY_COLORS[name] for name in strategy_order]

        bars = ax.bar(range(len(strategy_order)), values, color=colors)
        ax.set_xticks(range(len(strategy_order)))
        ax.set_xticklabels([str(i + 1) for i in range(len(strategy_order))])
        ax.set_xlabel("Strategy")
        ax.set_title(config.LOCATIONS[location]["name"])
        ax.grid(alpha=0.3, axis="y")

        for bar, value in zip(bars, values):
            ax.text(
                bar.get_x() + bar.get_width() / 2, bar.get_height(), f"{value:.0f}",
                ha="center", va="bottom", fontsize=8,
            )

    axes[0].set_ylabel("coldstart_count [per year]")
    fig.legend(
        handles=[plt.Rectangle((0, 0), 1, 1, color=STRATEGY_COLORS[s.name]) for s in ALL_STRATEGIES],
        labels=display_names,
        loc="lower center",
        ncol=4,
        bbox_to_anchor=(0.5, -0.08),
        fontsize=8,
    )
    fig.suptitle("Strategy Comparison by Location (perfect forecast)")
    fig.tight_layout()
    return fig


def plot_uptime_comparison(sweep_df: pd.DataFrame, locations: list) -> plt.Figure:
    """
    Figure 5 (supplementary -- per the user's request): the same layout as
    figure 1 (main figure), but shows reactor_warm_fraction_pct (the
    "uptime", i.e. the percentage of the year during which the reactor was
    actually producing) instead of coldstart_count. The two figures are
    best viewed together: coldstart_count shows the number of events,
    while uptime shows how much total production loss these events caused
    -- the two are not necessarily proportional to each other (e.g. fewer
    but longer cold starts can cause the same or more production loss
    than more numerous but shorter ones).
    """
    subset_all = sweep_df[sweep_df["forecast_error_std"] == 0.0]
    strategy_order = [s.name for s in ALL_STRATEGIES]
    display_names = [s.display_name for s in ALL_STRATEGIES]

    fig, axes = plt.subplots(1, len(locations), figsize=(5.5 * len(locations), 5.5), sharey=False)
    if len(locations) == 1:
        axes = [axes]

    for ax, location in zip(axes, locations):
        subset = subset_all[subset_all["location"] == location].set_index("strategy")
        values = [
            subset.loc[name, "reactor_warm_fraction_pct"] if name in subset.index else np.nan
            for name in strategy_order
        ]
        colors = [STRATEGY_COLORS[name] for name in strategy_order]

        bars = ax.bar(range(len(strategy_order)), values, color=colors)
        ax.set_xticks(range(len(strategy_order)))
        ax.set_xticklabels([str(i + 1) for i in range(len(strategy_order))])
        ax.set_xlabel("Strategy")
        ax.set_title(config.LOCATIONS[location]["name"])
        ax.grid(alpha=0.3, axis="y")

        for bar, value in zip(bars, values):
            ax.text(
                bar.get_x() + bar.get_width() / 2, bar.get_height(), f"{value:.1f}",
                ha="center", va="bottom", fontsize=8,
            )

    axes[0].set_ylabel("reactor uptime [% of year actually producing]")
    fig.legend(
        handles=[plt.Rectangle((0, 0), 1, 1, color=STRATEGY_COLORS[s.name]) for s in ALL_STRATEGIES],
        labels=display_names,
        loc="lower center",
        ncol=4,
        bbox_to_anchor=(0.5, -0.08),
        fontsize=8,
    )
    fig.suptitle("Reactor Uptime by Location (perfect forecast)")
    fig.tight_layout()
    return fig


def plot_robustness_by_strategy(sweep_df: pd.DataFrame, location: str) -> plt.Figure:
    """Figure 2 (robustness figure): coldstart_count vs. forecast_error_std, 7 lines, for one location."""
    fig, ax = plt.subplots(figsize=(8, 6))
    subset_loc = sweep_df[sweep_df["location"] == location]

    for strategy_class in ALL_STRATEGIES:
        line = subset_loc[subset_loc["strategy"] == strategy_class.name].sort_values("forecast_error_std")
        ax.plot(
            line["forecast_error_std"], line["coldstart_count"],
            marker="o", color=STRATEGY_COLORS[strategy_class.name], label=strategy_class.display_name,
        )

    ax.set_xlabel("forecast_error_std [fraction of PV capacity]")
    ax.set_ylabel("coldstart_count [per year]")
    ax.set_title(f"Robustness to Forecast Error -- {config.LOCATIONS[location]['name']}")
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    return fig


def plot_complexity_vs_effectiveness(sweep_df: pd.DataFrame, location: str) -> plt.Figure:
    """Figure 3 (complexity vs. effectiveness): 7 labeled points."""
    fig, ax = plt.subplots(figsize=(8, 6))
    subset = sweep_df[(sweep_df["location"] == location) & (sweep_df["forecast_error_std"] == 0.0)]

    for strategy_class in ALL_STRATEGIES:
        row = subset[subset["strategy"] == strategy_class.name]
        if len(row) == 0:
            continue
        complexity = row["complexity"].iloc[0]
        coldstart = row["coldstart_count"].iloc[0]
        ax.scatter(complexity, coldstart, s=140, color=STRATEGY_COLORS[strategy_class.name], zorder=3)
        ax.annotate(
            strategy_class.display_name.split(". ", 1)[-1],
            (complexity, coldstart),
            textcoords="offset points",
            xytext=(8, 6),
            fontsize=9,
        )

    ax.set_xlabel("Complexity [1 = simplest, 5 = most sophisticated]")
    ax.set_ylabel(f"coldstart_count [per year] -- {config.LOCATIONS[location]['name']}")
    ax.set_title("Complexity vs. Effectiveness")
    ax.set_xlim(0.5, 5.5)
    ax.set_xticks([1, 2, 3, 4, 5])
    ax.grid(alpha=0.3)
    fig.tight_layout()
    return fig


def plot_critical_period_all_strategies(location: str, weather_df: pd.DataFrame) -> plt.Figure:
    """
    Figure 4 (critical period time series): runs all 7 strategies
    individually for the same location (with perfect forecast), finds the
    worst 30-day period (according to the Reactive Baseline run, used as
    the reference), and plots every strategy's reactor temperature
    together over that period.
    """
    results = {}
    for strategy_class in ALL_STRATEGIES:
        results[strategy_class.name] = simulate_with_strategy(weather_df, location, strategy_class, forecast_error_std=0.0)

    baseline_df = results["reactive_baseline"]
    start, end = find_critical_period(baseline_df, window_days=30)

    fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True)

    # --- Top panel: PV + the Reactive Baseline's BESS state of charge (as reference) ---
    b = baseline_df.loc[start:end]
    axes[0].fill_between(b.index, b["pv_power_kw"], color="#fbbf24", alpha=0.35, label="PV output [kW]")
    axes[0].set_ylabel("PV output [kW]")
    ax0b = axes[0].twinx()
    for strategy_class in ALL_STRATEGIES:
        s = results[strategy_class.name].loc[start:end]
        ax0b.plot(
            s.index, s["bess_soc_fraction"] * 100, color=STRATEGY_COLORS[strategy_class.name],
            linewidth=1.0, alpha=0.85, label=strategy_class.display_name,
        )
    ax0b.set_ylabel("Battery SOC [%]")
    ax0b.set_ylim(0, 100)
    axes[0].set_title(f"Critical Period -- {config.LOCATIONS[location]['name']} ({start:%Y-%m-%d} to {end:%Y-%m-%d})")
    axes[0].grid(alpha=0.3)

    # --- Middle panel: reactor temperature, all 7 strategies ---
    for strategy_class in ALL_STRATEGIES:
        s = results[strategy_class.name].loc[start:end]
        axes[1].plot(
            s.index, s["reactor_temperature_c"], color=STRATEGY_COLORS[strategy_class.name],
            linewidth=1.2, label=strategy_class.display_name,
        )
    axes[1].axhline(config.SABATIER_MIN_TEMP_C, color="#78716c", linestyle="--", linewidth=1)
    axes[1].set_ylabel("Reactor temp. [°C]")
    axes[1].legend(loc="lower right", fontsize=7, ncol=2)
    axes[1].grid(alpha=0.3)

    # --- Bottom panel: which strategy was "active" (life-insurance mode) ---
    for i, strategy_class in enumerate(ALL_STRATEGIES):
        s = results[strategy_class.name].loc[start:end]
        active = s["reserve_active"].astype(int)
        axes[2].fill_between(
            s.index, i, i + active, step="post", color=STRATEGY_COLORS[strategy_class.name],
        )
    axes[2].set_yticks([i + 0.5 for i in range(len(ALL_STRATEGIES))])
    axes[2].set_yticklabels([s.display_name for s in ALL_STRATEGIES], fontsize=8)
    axes[2].set_xlabel("Time")
    axes[2].set_title("Active protection, by strategy")
    axes[2].grid(alpha=0.3)

    fig.tight_layout()
    return fig


def main() -> None:
    sweep_path = config.STRATEGY_RESULTS_DIR / "strategy_sweep_results.csv"
    if not sweep_path.exists():
        raise FileNotFoundError(
            f"Sweep result file not found: {sweep_path}. "
            f"Run this first: python simulation/strategy_sweep.py"
        )
    sweep_df = pd.read_csv(sweep_path)
    locations = config.SWEEP_LOCATIONS

    print("--- Figure 1: strategy comparison per location (coldstart_count) ---")
    fig1 = plot_strategy_comparison_bars(sweep_df, locations)
    out1 = config.STRATEGY_RESULTS_DIR / "fig1_strategy_comparison.png"
    fig1.savefig(out1, dpi=140, bbox_inches="tight")
    print(f"  saved -> {out1}")

    print("\n--- Figure 5 (supplementary): strategy comparison per location (uptime) ---")
    fig5 = plot_uptime_comparison(sweep_df, locations)
    out5 = config.STRATEGY_RESULTS_DIR / "fig5_uptime_comparison.png"
    fig5.savefig(out5, dpi=140, bbox_inches="tight")
    print(f"  saved -> {out5}")

    print("\n--- Figure 2: robustness (Edinburgh) ---")
    fig2 = plot_robustness_by_strategy(sweep_df, "scotland")
    out2 = config.STRATEGY_RESULTS_DIR / "fig2_robustness.png"
    fig2.savefig(out2, dpi=140)
    print(f"  saved -> {out2}")

    print("\n--- Figure 3: complexity vs. effectiveness (Edinburgh) ---")
    fig3 = plot_complexity_vs_effectiveness(sweep_df, "scotland")
    out3 = config.STRATEGY_RESULTS_DIR / "fig3_complexity_vs_effectiveness.png"
    fig3.savefig(out3, dpi=140)
    print(f"  saved -> {out3}")

    print("\n--- Figure 4: critical period (Sevilla + Edinburgh) ---")
    for location in ["sevilla", "scotland"]:
        weather = pd.read_csv(config.LOCATIONS[location]["weather_csv"], index_col=0, parse_dates=True)
        fig4 = plot_critical_period_all_strategies(location, weather)
        out4 = config.STRATEGY_RESULTS_DIR / f"fig4_critical_period_{location}.png"
        fig4.savefig(out4, dpi=140)
        print(f"  {location} saved -> {out4}")

    print("\n--- Summary table (coldstart + uptime, with perfect forecast) ---")
    summary = sweep_df[sweep_df["forecast_error_std"] == 0.0]
    table = summary.pivot_table(
        index="strategy_display_name",
        columns="location",
        values=["coldstart_count", "reactor_warm_fraction_pct"],
    ).reindex([s.display_name for s in ALL_STRATEGIES])
    print(table.round(1).to_string())

    print("\nDone.")


if __name__ == "__main__":
    main()
