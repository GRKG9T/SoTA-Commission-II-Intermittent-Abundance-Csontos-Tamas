"""
run_strategy_comparison.py -- Single entry point: full end-to-end
comparison of the 7 BESS control strategies.

Runs:
    1. simulation/strategy_sweep.py -- the 84-combination sweep
       (7 strategies x 3 locations x 4 forecast_error values)
    2. analysis/strategy_comparison.py -- all 4 requested figures

All results go into the results/strategy_comparison/ folder (CSV + PNG).

Usage:
    python run_strategy_comparison.py
"""

import time

import config
from analysis.strategy_comparison import main as run_analysis_main
from simulation.strategy_sweep import main as run_sweep_main

if __name__ == "__main__":
    print("=" * 72)
    print("Comparison of 7 BESS control strategies")
    print("=" * 72)
    print()

    t0 = time.time()

    print("[1/2] Running the parameter sweep (84 = 7 x 3 x 4 combinations)...\n")
    run_sweep_main()

    print("\n[2/2] Producing figures...\n")
    run_analysis_main()

    elapsed = time.time() - t0
    print(f"\nTotal runtime: {elapsed:.0f} seconds.")
    print(f"All results can be found here: {config.STRATEGY_RESULTS_DIR}")
