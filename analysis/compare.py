"""
analysis/compare.py -- Comparison of baseline vs. proactive controller

Generates the 1st and 2nd required figures according to chapter 7.1 of the
documentation:
    1. Critical period time series (the worst 7-day period in the baseline)
    2. Comparison table figure (all metrics, with % improvement)

Usage:
    python analysis/compare.py [--location sevilla]
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
from analysis.plots import find_critical_period, plot_comparison_table, plot_critical_period
from simulation.baseline_sim import compute_metrics, simulate_baseline
from simulation.smart_sim import simulate_smart

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Baseline vs. proactive comparison")
    parser.add_argument("--location", default="sevilla", choices=list(config.LOCATIONS.keys()))
    args = parser.parse_args()
    location = args.location
    location_name = config.LOCATIONS[location]["name"]

    print(f"Baseline vs. proactive comparison -- {location_name}\n")

    weather = pd.read_csv(config.LOCATIONS[location]["weather_csv"], index_col=0, parse_dates=True)

    print("Running baseline simulation...")
    baseline_df = simulate_baseline(weather, location)
    baseline_metrics = compute_metrics(baseline_df)

    print("Running proactive simulation...")
    smart_df = simulate_smart(weather, location)
    smart_metrics = compute_metrics(smart_df)

    print(f"\nBaseline coldstart_count: {baseline_metrics['coldstart_count']}")
    print(f"Proactive coldstart_count: {smart_metrics['coldstart_count']}\n")

    start, end = find_critical_period(baseline_df, window_days=7)
    print(f"Critical period (the baseline's worst 7 days): {start:%Y-%m-%d %H:%M} -- {end:%Y-%m-%d %H:%M}")

    fig1 = plot_critical_period(baseline_df, smart_df, start, end, location_name=location_name)
    out1 = config.RESULTS_DIR / f"fig1_critical_period_{location}.png"
    fig1.savefig(out1, dpi=140)
    print(f"Figure 1 saved: {out1}")

    fig2 = plot_comparison_table(baseline_metrics, smart_metrics)
    out2 = config.RESULTS_DIR / f"fig2_comparison_table_{location}.png"
    fig2.savefig(out2, dpi=140, bbox_inches="tight")
    print(f"Figure 2 saved: {out2}")
