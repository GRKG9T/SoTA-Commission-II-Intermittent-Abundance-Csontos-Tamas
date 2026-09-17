"""
run_smart.py -- Running the proactive (life insurance) controller from the command line

Thin entry point for simulation/smart_sim.py -- see also the note in
run_baseline.py.

Usage:
    python run_smart.py --location sevilla --threshold 24 --reserve 0.25
"""

import argparse

import config
from simulation.smart_sim import main as run_smart_main

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the proactive (life insurance) simulation")
    parser.add_argument(
        "--location",
        default="sevilla",
        choices=list(config.LOCATIONS.keys()),
        help="Which location to run the simulation for",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=config.THRESHOLD_HOURS,
        help="threshold_hours -- length of the forecast lookahead in hours",
    )
    parser.add_argument(
        "--reserve",
        type=float,
        default=config.RESERVE_FRACTION,
        help="reserve_fraction -- safety threshold as a fraction of BESS capacity",
    )
    args = parser.parse_args()

    run_smart_main(location=args.location, threshold_hours=args.threshold, reserve_fraction=args.reserve)
