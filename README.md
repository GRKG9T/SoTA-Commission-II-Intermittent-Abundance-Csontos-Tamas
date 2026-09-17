# BESS as process life insurance

Proactive thermal-state preservation via simulation-based optimization
— SOTA Commission II: Intermittent Abundance

## What does this project do?

A digital twin of a remote, solar-powered synthetic methane production
plant. The project demonstrates how **proactive**, weather-forecast-based
capacity reservation by the BESS (battery energy storage system) prevents
the Sabatier reactor from cooling down — avoiding the 4-6 hour cold-start
loss that a conventional ("naive") BESS controller fails to anticipate.

For the full technical background and the grant submission text, see `SOTA_Commission_II_Submission.docx`.

## Prerequisites

```bash
pip install pvlib pandas numpy matplotlib requests
```

(Python 3.10+ recommended.)

## Run order

**1. Download data** (only needed the first time):

```bash
python data_fetch/pvgis_fetch.py --all
```

This downloads PVGIS TMY weather data for all three locations (Seville,
Morocco, Scotland) into the `data/` folder.

**2. Baseline (naive) simulation:**

```bash
python run_baseline.py --location sevilla
```

**3. Proactive ("life insurance") controller:**

```bash
python run_smart.py --location sevilla --threshold 24 --reserve 0.25
```

**4. Full parameter sweep** (5x6x4x3 = 360 combinations, ~3-4 minutes):

```bash
python run_sweep.py
```

For a quick, small-grid test: `python run_sweep.py --quick`

**5. Analysis and figures** (after the sweep and baseline/smart runs):

```bash
python analysis/compare.py --location sevilla
python analysis/sweep_analysis.py
```

**6. Demo — this is what runs for the submission:**

```bash
python run_demo.py --location sevilla
```

Runs the full year with both controllers in a single command, finds the
most critical 30-day period, and produces the presentation figures.

**7. Strategy comparison — the project's main comparative analysis:**

```bash
python run_strategy_comparison.py
```

Runs a systematic comparison of **7 different BESS control strategies**
(reactive baseline, fixed reserve, forecast-driven binary, proportional
reserve, temperature-based, precharge, rolling horizon — see
`control/strategies/`) across all 3 locations and 4 forecast-error
levels (84 full-year simulations, ~40 seconds total), and produces 5
comparison figures plus a results CSV in `results/strategy_comparison/`.
This answers the project's central question: *which* life-insurance
strategy works when, and is the extra complexity worth it?

## Results

The output of every run (hourly CSV + PNG figures) goes into the
`results/` folder.

The key figures:

| File | Contents |
|---|---|
| `demo_critical_period_<location>.png` | 30-day critical period: PV, BESS state of charge, reactor temperature, life insurance status (baseline vs. proactive) |
| `demo_comparison_table_<location>.png` | Table of annual metrics, with percentage improvement |
| `fig3_heatmap_<location>.png` | Optimization heatmap (threshold_hours x reserve_fraction x coldstart_count) |
| `fig4_robustness_curve.png` | Robustness under forecast error, by location |
| `sweep_results_full.csv` | Raw results of the full 360-combination sweep |
| `strategy_comparison/fig1_strategy_comparison.png` | Main figure: cold-start count by strategy, per location |
| `strategy_comparison/fig2_robustness.png`, `fig3_complexity_vs_effectiveness.png`, `fig5_uptime_comparison.png` | Supporting figures: robustness to forecast error, complexity vs. effectiveness, reactor uptime by strategy |
| `strategy_comparison/fig4_critical_period_<location>.png` | Critical-period time series with all 7 strategies overlaid |
| `strategy_comparison/strategy_sweep_results.csv` | Raw results of all 84 strategy-comparison runs |

## Project structure

```
config.py                 # Global parameters
data_fetch/                # PVGIS data downloader
models/                    # PV, BESS, Sabatier, electrolyzer, DAC models
control/                    # RTU layer + life insurance controller
control/strategies/         # 7 BESS control strategies behind a shared interface
simulation/                 # Baseline, proactive, sweep, and strategy-sweep simulations
analysis/                   # Visualization and comparison modules
run_baseline.py, run_smart.py, run_sweep.py, run_demo.py, run_strategy_comparison.py   # Command-line entry points
results/                    # Output of every run (CSV + PNG)
```

## Simplifications (see also chapter 9 of the documentation)

- The Sabatier cooling model only models cooling, not the reaction heat
  — this is a conservative estimate.
- The BESS model does not include degradation.
- Forecast error is modeled as additive Gaussian noise (not
  time-correlated).
