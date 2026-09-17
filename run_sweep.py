"""
run_sweep.py -- Running the full parameter sweep from the command line

Thin entry point for simulation/sweep_sim.py -- see also the note in
run_baseline.py. By default it runs the full 360-combination sweep
(about 3-4 minutes on this machine) -- this requires the weather data
for all three locations to already be downloaded (see
data_fetch/pvgis_fetch.py --all).

Usage:
    python run_sweep.py            # full sweep (360 combinations)
    python run_sweep.py --quick    # small test grid, Sevilla only
"""

import argparse

from simulation.sweep_sim import main as run_sweep_main

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the parameter sweep")
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Small test grid (2x2x1 combinations, Sevilla only) for quickly checking the logic",
    )
    args = parser.parse_args()

    run_sweep_main(quick=args.quick)
