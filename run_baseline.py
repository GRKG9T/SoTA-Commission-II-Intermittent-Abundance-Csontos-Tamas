"""
run_baseline.py -- Running the baseline (naive) controller from the command line

This is a thin "entry point": the actual simulation logic lives in
simulation/baseline_sim.py, this file is provided just for convenient
command-line use as documented in the README.

Usage:
    python run_baseline.py --location sevilla
"""

import argparse

import config
from simulation.baseline_sim import main as run_baseline_main

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the baseline (naive) simulation")
    parser.add_argument(
        "--location",
        default="sevilla",
        choices=list(config.LOCATIONS.keys()),
        help="Which location to run the simulation for",
    )
    args = parser.parse_args()

    run_baseline_main(location=args.location)
