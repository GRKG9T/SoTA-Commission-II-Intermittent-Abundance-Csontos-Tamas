"""
analysis/sweep_analysis.py -- Analysis of the parameter sweep results

Generates the 3rd and 4th required figures according to chapter 7.1 of the
documentation:
    3. Optimization heatmap -- a separate figure for each of the three locations
    4. Robustness curve -- as a function of forecast_error_std, per location

Usage:
    python analysis/sweep_analysis.py [--sweep-file results/sweep_results_full.csv]
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
from analysis.plots import plot_optimization_heatmap, plot_robustness_curve

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analysis and visualization of sweep results")
    parser.add_argument(
        "--sweep-file",
        default=str(config.RESULTS_DIR / "sweep_results_full.csv"),
        help="Path to the result CSV saved by sweep_sim.py",
    )
    args = parser.parse_args()

    sweep_path = Path(args.sweep_file)
    if not sweep_path.exists():
        raise FileNotFoundError(
            f"Sweep result file not found: {sweep_path}. "
            f"Run this first: python simulation/sweep_sim.py"
        )

    print(f"Loading sweep results: {sweep_path}\n")
    sweep_df = pd.read_csv(sweep_path)

    locations_present = [loc for loc in config.SWEEP_LOCATIONS if loc in sweep_df["location"].unique()]

    print("--- Figure 3: optimization heatmap per location ---")
    for location in locations_present:
        fig = plot_optimization_heatmap(sweep_df, location)
        out = config.RESULTS_DIR / f"fig3_heatmap_{location}.png"
        fig.savefig(out, dpi=140)
        print(f"  {location:<8} -> {out}")

    print("\n--- Figure 4: robustness curve ---")
    fig4 = plot_robustness_curve(sweep_df, locations_present)
    out4 = config.RESULTS_DIR / "fig4_robustness_curve.png"
    fig4.savefig(out4, dpi=140)
    print(f"  saved -> {out4}")

    # --- Short text summary: optimal combination per location ---
    print("\n--- Optimal combination per location (with perfect forecast) ---")
    zero_error = sweep_df[sweep_df["forecast_error_std"] == 0.0]
    for location in locations_present:
        subset = zero_error[zero_error["location"] == location]
        best = subset.loc[subset["coldstart_count"].idxmin()]
        print(
            f"  {location:<8} threshold_hours={best['threshold_hours']:>2.0f}, "
            f"reserve_fraction={best['reserve_fraction']:.2f} -> "
            f"coldstart_count={best['coldstart_count']:.0f}"
        )
