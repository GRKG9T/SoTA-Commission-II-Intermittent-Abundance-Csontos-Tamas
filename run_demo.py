"""
run_demo.py -- 30-day demo for the grant submission

This is the only file you need to run for the demonstration. For a
given location (Sevilla by default), it runs both the baseline (naive)
and the proactive (life insurance) simulation for the full year, finds
the worst 30-day period, and produces the two main demo figures
(critical period time series + comparison table), the same way
analysis/compare.py does for the 7-day version (step 10) -- except here
we show a 30-day, full-scope critical period, per chapter 11 of the
documentation.

All results (hourly CSV + PNG figures) go into the results/ folder.

Usage:
    python run_demo.py [--location sevilla]
"""

import argparse

import pandas as pd

import config
from analysis.plots import METRIC_LABELS, find_critical_period, plot_comparison_table, plot_critical_period
from simulation.baseline_sim import compute_metrics, simulate_baseline
from simulation.smart_sim import simulate_smart


def main(location: str = "sevilla") -> None:
    location_name = config.LOCATIONS[location]["name"]

    print("=" * 72)
    print("SOTA Commission II -- Intermittent Abundance")
    print("BESS as process life insurance -- 30-day demo")
    print(f"Location: {location_name}")
    print("=" * 72)
    print()

    weather = pd.read_csv(config.LOCATIONS[location]["weather_csv"], index_col=0, parse_dates=True)

    print("[1/4] Running baseline (naive) simulation (full year)...")
    baseline_df = simulate_baseline(weather, location)
    baseline_metrics = compute_metrics(baseline_df)

    print("[2/4] Running proactive (life insurance) simulation (full year)...")
    smart_df = simulate_smart(weather, location)
    smart_metrics = compute_metrics(smart_df)

    baseline_csv = config.RESULTS_DIR / f"demo_baseline_{location}_hourly.csv"
    smart_csv = config.RESULTS_DIR / f"demo_smart_{location}_hourly.csv"
    baseline_df.to_csv(baseline_csv)
    smart_df.to_csv(smart_csv)
    print(f"      Hourly results saved: {baseline_csv.name}, {smart_csv.name}")

    print("[3/4] Finding the most critical 30-day period in the baseline...")
    start, end = find_critical_period(baseline_df, window_days=30)
    print(f"      Selected period: {start:%Y-%m-%d} -- {end:%Y-%m-%d}")

    print("[4/4] Producing demo figures...")
    fig1 = plot_critical_period(baseline_df, smart_df, start, end, location_name=location_name)
    out1 = config.RESULTS_DIR / f"demo_critical_period_{location}.png"
    fig1.savefig(out1, dpi=140)

    fig2 = plot_comparison_table(baseline_metrics, smart_metrics)
    out2 = config.RESULTS_DIR / f"demo_comparison_table_{location}.png"
    fig2.savefig(out2, dpi=140, bbox_inches="tight")
    print(f"      Saved: {out1.name}, {out2.name}")

    print()
    print("=" * 72)
    print("ANNUAL SUMMARY")
    print("=" * 72)
    print(f"{'Metric':<30}{'Baseline':>14}{'Proactive':>14}")
    print("-" * 58)
    for key, (label, unit, _) in METRIC_LABELS.items():
        b_val = baseline_metrics[key]
        s_val = smart_metrics[key]
        print(f"{label + ' [' + unit + ']':<30}{b_val:>14,.0f}{s_val:>14,.0f}")

    coldstart_baseline = baseline_metrics["coldstart_count"]
    coldstart_smart = smart_metrics["coldstart_count"]
    print()
    print("=" * 72)
    if coldstart_baseline > 0:
        reduction_pct = (1 - coldstart_smart / coldstart_baseline) * 100
        print(
            f"KEY RESULT: with the conventional (naive) BESS controller, {coldstart_baseline} "
            f"cold starts occurred over one year in {location_name}'s climate."
        )
        print(
            f"With the proactive, weather-forecast-based \"life insurance\" controller, this "
            f"dropped to {coldstart_smart} -- a {reduction_pct:.0f}% improvement,"
        )
        print("by avoiding the Sabatier reactor cooling down and the 4-6 hour cold-start loss it causes.")
    else:
        print(f"KEY RESULT: in {location_name}'s climate, both controllers achieved 0 cold starts.")
    print("=" * 72)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="30-day demo for the SOTA Commission II submission")
    parser.add_argument(
        "--location",
        default="sevilla",
        choices=list(config.LOCATIONS.keys()),
        help="Which location to run the demo for",
    )
    args = parser.parse_args()

    main(location=args.location)
