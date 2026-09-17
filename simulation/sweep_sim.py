"""
simulation/sweep_sim.py -- Parametric sweep (the heart of the project)

Iterates over the threshold_hours x reserve_fraction x forecast_error_std x
location parameter space, and for every combination runs the full-year
proactive (life insurance) simulation. The full sweep consists of
5 x 6 x 4 x 3 = 360 runs (see config.py: SWEEP_THRESHOLD_HOURS,
SWEEP_RESERVE_FRACTION, SWEEP_FORECAST_ERROR_STD, SWEEP_LOCATIONS).

Goal: find the optimal (threshold_hours, reserve_fraction) pair, and show
how this depends on the location (section 5.4) and how robust it is to an
erring forecast (forecast_error_std > 0).

For every (location, forecast_error) pair, forecast_error_std uses the
same random noise realization (deterministic seed), regardless of what
threshold_hours/reserve_fraction currently is -- this way the runs are
cleanly comparable along the threshold/reserve axes, since the noise
realization does not interfere with the difference.

Usage:
    python simulation/sweep_sim.py --quick   # small grid, Sevilla only (fast, for testing)
    python simulation/sweep_sim.py           # full 360-combination sweep
"""

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
from simulation.baseline_sim import compute_metrics, simulate_baseline
from simulation.smart_sim import simulate_smart


def run_sweep(
    threshold_hours_list: list,
    reserve_fraction_list: list,
    forecast_error_list: list,
    location_list: list,
    verbose: bool = True,
) -> pd.DataFrame:
    """
    Runs the full parameter-space sweep, and returns the results in a
    DataFrame -- each row is the result of one (location, threshold_hours,
    reserve_fraction, forecast_error_std) combination: the parameters +
    the metrics per chapter 6.
    """
    total = len(threshold_hours_list) * len(reserve_fraction_list) * len(forecast_error_list) * len(location_list)
    records = []
    weather_cache = {}
    count = 0
    start_time = time.time()

    for location_key in location_list:
        if location_key not in weather_cache:
            weather_cache[location_key] = pd.read_csv(
                config.LOCATIONS[location_key]["weather_csv"], index_col=0, parse_dates=True
            )
        weather = weather_cache[location_key]

        for fe_index, forecast_error in enumerate(forecast_error_list):
            # Deterministic, but with a random seed unique to each
            # (location, forecast_error) pair -- see the explanation at
            # the top of the file.
            random_seed = config.RANDOM_SEED + location_list.index(location_key) * 100 + fe_index

            for threshold_hours in threshold_hours_list:
                for reserve_fraction in reserve_fraction_list:
                    count += 1
                    result = simulate_smart(
                        weather,
                        location_key,
                        threshold_hours=threshold_hours,
                        reserve_fraction=reserve_fraction,
                        forecast_error_std=forecast_error,
                        random_seed=random_seed,
                    )
                    metrics = compute_metrics(result)
                    records.append(
                        {
                            "location": location_key,
                            "threshold_hours": threshold_hours,
                            "reserve_fraction": reserve_fraction,
                            "forecast_error_std": forecast_error,
                            **metrics,
                        }
                    )
                    if verbose:
                        elapsed = time.time() - start_time
                        print(
                            f"[{count}/{total}] {location_key:<8} th={threshold_hours:>2} "
                            f"rf={reserve_fraction:.2f} fe={forecast_error:.1f} -> "
                            f"coldstart={metrics['coldstart_count']:>3}  "
                            f"({elapsed:.0f} s elapsed)"
                        )

    return pd.DataFrame(records)


def compute_baseline_reference(location_list: list) -> pd.DataFrame:
    """The baseline (naive) metrics per location -- this does not depend
    on the sweep's parameters, so it is only calculated once per location,
    for the later comparison (analysis/compare.py, step 10)."""
    records = []
    for location_key in location_list:
        weather = pd.read_csv(config.LOCATIONS[location_key]["weather_csv"], index_col=0, parse_dates=True)
        result = simulate_baseline(weather, location_key)
        metrics = compute_metrics(result)
        records.append({"location": location_key, **metrics})
    return pd.DataFrame(records)


def main(quick: bool = False) -> None:
    if quick:
        print("QUICK TEST MODE: small grid, Sevilla only\n")
        threshold_hours_list = [12, 24]
        reserve_fraction_list = [0.10, 0.25]
        forecast_error_list = [0.0]
        location_list = ["sevilla"]
    else:
        print("FULL SWEEP: all 5x6x4x3 = 360 combinations, all three locations\n")
        threshold_hours_list = config.SWEEP_THRESHOLD_HOURS
        reserve_fraction_list = config.SWEEP_RESERVE_FRACTION
        forecast_error_list = config.SWEEP_FORECAST_ERROR_STD
        location_list = config.SWEEP_LOCATIONS

    n_combos = len(threshold_hours_list) * len(reserve_fraction_list) * len(forecast_error_list) * len(location_list)
    print(f"Number of combinations: {n_combos}\n")

    print("Calculating baseline (naive) reference values per location...")
    baseline_ref = compute_baseline_reference(location_list)
    print(baseline_ref[["location", "coldstart_count"]].to_string(index=False))
    print()

    t0 = time.time()
    results_df = run_sweep(threshold_hours_list, reserve_fraction_list, forecast_error_list, location_list)
    elapsed = time.time() - t0
    print(f"\nSweep done: {len(results_df)} runs, in {elapsed:.0f} seconds.")

    suffix = "quick" if quick else "full"
    out_csv = config.RESULTS_DIR / f"sweep_results_{suffix}.csv"
    results_df.to_csv(out_csv, index=False)
    print(f"Results saved: {out_csv}")

    baseline_csv = config.RESULTS_DIR / f"sweep_baseline_reference_{suffix}.csv"
    baseline_ref.to_csv(baseline_csv, index=False)
    print(f"Baseline reference saved: {baseline_csv}")

    # --- Quick summary: best (fewest coldstart) combination per location ---
    print("\nBest (fewest coldstart_count) combination per location (at forecast_error=0.0):")
    zero_error = results_df[results_df["forecast_error_std"] == 0.0]
    for location_key in location_list:
        subset = zero_error[zero_error["location"] == location_key]
        if len(subset) == 0:
            continue
        best = subset.loc[subset["coldstart_count"].idxmin()]
        print(
            f"  {location_key:<8} threshold_hours={best['threshold_hours']:>2}, "
            f"reserve_fraction={best['reserve_fraction']:.2f} -> "
            f"coldstart_count={best['coldstart_count']:.0f}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Parametric sweep -- life insurance controller")
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Small test grid (2x2x1 combinations, Sevilla only) for a quick check of the logic",
    )
    args = parser.parse_args()
    main(quick=args.quick)
