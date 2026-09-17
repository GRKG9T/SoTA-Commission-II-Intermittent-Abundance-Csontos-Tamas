# User Guide

This guide shows you what each file does, how to run simulations, and
how to modify data/settings yourself, without Claude Code.

> For the full technical background of the project, see `SOTA_Commission_II_Submission.docx`.
> For the bare run commands, see [README.md](README.md).
> This file explains **what happens behind the scenes**, and **what's
> worth modifying** if you want something to work differently.

---

## 1. Quick start

If you just want to run something, these are the most common commands:

```bash
# One-time step: download weather data (if not already in the data/ folder)
python data_fetch/pvgis_fetch.py --all

# The main demo: full year, both controllers, critical-period figure
python run_demo.py --location sevilla

# Full parameter sweep (360 combinations, about 3-4 minutes)
python run_sweep.py

# The 7-strategy comparison (the project's main analysis, ~40 seconds)
python run_strategy_comparison.py
```

Every result (CSV + PNG) goes into the `results/` folder.

---

## 2. Folder structure overview

```
config.py                  <- this is where the settings live (you'll modify this most often)
data/                      <- downloaded weather data (CSV)
data_fetch/                <- data-download script
models/                    <- models of the individual physical components
control/                   <- control logic (RTU + life insurance)
simulation/                <- scripts that tie the models together and run a full year
analysis/                  <- figure-generating and comparison scripts
run_*.py                   <- command-line entry points (these are what you run)
results/                   <- ALL output (CSV + PNG) goes here
```

**An important rule that runs through the whole project:** every file
that uses a parameter (e.g. `BESS_CAPACITY_KWH`) imports it from
`config.py`. There are no "hard-coded" numbers inside the models
anywhere. This means: **if you want to change something, you almost
always need to look in `config.py`**, not in the individual model
files.

---

## 3. The 5 main runnable scripts

These live in the project root, and you run them from the command line.

### `run_baseline.py` -- the "naive" controller

```bash
python run_baseline.py --location sevilla
```

Runs the full year (8760 hours) with the conventional controller that
has no forecasting. Prints out the metrics, and saves the hourly result
(`baseline_<location>_hourly.csv`) and a check figure.

`--location`: `sevilla`, `morocco`, or `scotland`.

### `run_smart.py` -- the proactive "life insurance" controller

```bash
python run_smart.py --location sevilla --threshold 24 --reserve 0.25
```

Same as the baseline, but with the proactive controller, and it
immediately compares itself against the baseline. It has two parameters
of its own:

- `--threshold` (hours): how far ahead it should look in the forecast.
  Smaller value = more sensitive, intervenes earlier/more often.
- `--reserve` (fraction between 0 and 1): how much safety reserve to
  keep in the BESS above the physical minimum. Larger value = more
  conservative, fewer cold starts, but more lost production time.

### `run_sweep.py` -- the full parameter study

```bash
python run_sweep.py            # full 360 combinations (~3-4 minutes)
python run_sweep.py --quick    # small test grid, Seville only (a few seconds)
```

Goes through every (threshold, reserve, forecast error, location)
combination, and saves the result to `results/sweep_results_full.csv`.
**This requires the weather data for all three locations to already be
downloaded** (`python data_fetch/pvgis_fetch.py --all`).

### `run_demo.py` -- the demo script

```bash
python run_demo.py --location sevilla
```

Runs both controllers over a full year, finds the worst 30-day period,
and produces the two main presentation figures plus a text summary.
**This is the one file you run for the grant presentation.**

### `run_strategy_comparison.py` -- the 7-strategy comparison

```bash
python run_strategy_comparison.py
```

Runs `simulation/strategy_sweep.py` (7 strategies x 3 locations x 4
forecast-error levels = 84 full-year simulations, ~40 seconds) and then
`analysis/strategy_comparison.py` (5 figures) in one go. **This is the
project's main comparative analysis** -- it answers *which* life-insurance
strategy works best, where, and whether its complexity is worth it. See
section 5.3 below for what each of the 7 strategies actually does.

---

## 4. `config.py` -- the settings

This file is divided into sections. The table below shows **what to
modify if you want to...**

| If you want to... | Modify this parameter |
|---|---|
| Simulate a bigger/smaller PV array | `PV_CAPACITY_KW` |
| Simulate a bigger/smaller BESS | `BESS_CAPACITY_KWH`, `BESS_MAX_CHARGE_KW`, `BESS_MAX_DISCHARGE_KW` |
| Make the reactor respond differently | `SABATIER_TAU_HOURS` (cooling rate), `SABATIER_MAINTENANCE_KW`, `SABATIER_COLDSTART_KW/HOURS` |
| Simulate a bigger/smaller electrolyzer/DAC | `ELECTROLYZER_MAX_KW`, `DAC_POWER_KW` |
| The default life insurance threshold | `THRESHOLD_HOURS`, `RESERVE_FRACTION` (used by `run_smart.py` if you don't pass `--threshold`/`--reserve`) |
| The range explored by the sweep | `SWEEP_THRESHOLD_HOURS`, `SWEEP_RESERVE_FRACTION`, `SWEEP_FORECAST_ERROR_STD`, `SWEEP_LOCATIONS` |
| Add a new location | `LOCATIONS` dictionary (see section 6.1 below) |

**Workflow after changing a parameter:** edit `config.py` -> re-run the
script you want to use (e.g. `python run_baseline.py --location sevilla`).
There's no need to "recompile" or do anything else — Python reads
`config.py` fresh on every run.

### The sections in detail

| Section | What it contains |
|---|---|
| 0. Folder structure | `DATA_DIR`, `RESULTS_DIR` -- don't touch these, they're computed automatically |
| 1. Locations | Coordinates and file names for the 3 locations |
| 2. PV array | `PV_CAPACITY_KW`, `PV_TILT`, `PV_AZIMUTH`, `PV_EFFICIENCY`, `PV_GAMMA_PDC` |
| 3. BESS | Capacity, charge/discharge rate, min/max state of charge, efficiency |
| 4. Sabatier reactor | Temperature thresholds, cooling time constant, maintenance/cold-start power |
| 5. Electrolyzer | Load range + specific H2 energy demand |
| 6. DAC | Rated power, ramp time + specific CO2 energy demand |
| 7. Control parameters | Default values for `THRESHOLD_HOURS`, `RESERVE_FRACTION` |
| 8. Sweep values | The ranges covered by the parameter study |
| 9. Stoichiometry | H2->CH4 conversion for estimating methane output (don't modify — these are physical constants) |
| 10. Strategy-comparison parameters | Defaults for the 7 compared strategies: `FIXED_RESERVE_FRACTION`, `PROPORTIONAL_MIN/MAX_RESERVE_FRACTION`, `PRECHARGE_TRIGGER_FRACTION`, `STRATEGY_COMPLEXITY` (the 1-5 complexity score used in figure 3) |

---

## 5. Modules by folder

### 5.1 `data_fetch/` -- data download

**`pvgis_fetch.py`** -- downloads the PVGIS TMY weather data for one (or
all three) locations, and saves it as CSV into the `data/` folder.

```bash
python data_fetch/pvgis_fetch.py --location morocco   # one location
python data_fetch/pvgis_fetch.py --all                # all three
```

You only need to run this again if you deleted the `data/` folder, or
added a new location to the `LOCATIONS` dictionary in `config.py`.

### 5.2 `models/` -- physical models of the individual components

Every file can also be run on its own (`python models/<file>.py`), which
triggers a built-in self-test that shows the model behaves sensibly.
This is useful if you've changed something in `config.py` and want to
check that the given component still works correctly.

| File | What it models | Self-test (`python models/<file>.py`) |
|---|---|---|
| `pv_model.py` | Solar array output (pvlib) | Annual production curve, checks that it falls within the 1700-2200 kWh/kWp range |
| `bess_model.py` | BESS charge/discharge, state of charge | Test of the charge limit, saturation, discharge, and reserve-blocking |
| `sabatier_model.py` | Reactor temperature state machine | Cooling curve, maintenance, cold-start timing |
| `electrolyzer_model.py` | H2 production from power | Turndown, max load, on/off switching |
| `dac_model.py` | CO2 capture, ramped consumption | Ramp up/down, energy limit |

### 5.3 `control/` -- control logic

| File | What it does |
|---|---|
| `rtu_layer.py` | **`RTULayer`** -- enforces hard physical limits (BESS min/max, load maximums, reserve lock). Every command passes through this before it is executed. |
| `controller.py` | **`LifeInsuranceController`** -- the brain of the proactive controller. Every hour it projects the BESS state-of-charge trajectory forward, and if the trajectory would fall below the safety threshold, it activates "life insurance" mode (shuts down the electrolyzer/DAC, protects reactor maintenance power). |

If you want to change the control **strategy** (e.g. have it decide on
activation based on different logic), you need to edit the `decide()`,
`_calculate_deficit()`, and `_calculate_reserve_needed()` methods in
`controller.py`. If you only want to change the **parameters**, it's
enough to edit `config.py` (`THRESHOLD_HOURS`, `RESERVE_FRACTION`).

### 5.3b `control/strategies/` -- the 7 compared control strategies

This is where the project's main comparative analysis lives. Every
strategy is a small class implementing a common `decide()` interface
(defined once in `base_strategy.py`), so `simulation/strategy_sweep.py`
can run any of them through the exact same simulation loop -- only the
strategy changes, everything else (models, RTU layer) stays identical.

| File | Strategy | What it does |
|---|---|---|
| `base_strategy.py` | (shared base class) | Common `decide()` interface, the shared reactor-command logic, and the forecast-window/net-balance-deficit helpers every strategy can use. |
| `reactive_baseline.py` | 1. Reactive Baseline | No forecast, no reserve -- electrolyzer/DAC always on. The reference point for every comparison. |
| `fixed_reserve.py` | 2. Fixed Reserve | No forecast needed -- always shuts down industrial loads below a fixed state-of-charge threshold. |
| `forecast_binary.py` | 3. Forecast Binary | Forecast-driven on/off switch with a fixed reserve size, based on a simple aggregate deficit check. |
| `proportional_reserve.py` | 4. Proportional Reserve | Reserve size scales continuously with forecast deficit severity, combined with a full state-of-charge trajectory projection. |
| `temperature_based.py` | 5. Temperature-Based | Computes the reserve from reactor physics (Newton's law of cooling) instead of a fixed/proportional fraction -- see the file's docstring for a documented formula bug that was found and fixed during development. |
| `precharge.py` | 6. Precharge | Activates earlier/more eagerly than the others, based on the forecast's mean PV level rather than a computed deficit. |
| `rolling_horizon.py` | 7. Rolling Horizon | The most sophisticated strategy -- re-projects the full state-of-charge trajectory every hour with the latest forecast (most compute, best handling of forecast error). |

To add an 8th strategy: create a new file following the same pattern
(subclass `BaseStrategy`, implement `decide()`), then add it to
`ALL_STRATEGIES` in `control/strategies/__init__.py`.

### 5.4 `simulation/` -- the full annual simulations

| File | What it does |
|---|---|
| `baseline_sim.py` | Ties together all the models with the naive controller. This is also where `compute_metrics()` lives, which calculates the 7 metrics -- used by `smart_sim.py`, `sweep_sim.py`, and `strategy_sweep.py` as well. |
| `smart_sim.py` | Same thing, but with the `LifeInsuranceController`. This is also where forecast error (Gaussian noise) is injected (`forecast_error_std` parameter). |
| `sweep_sim.py` | Goes through the full parameter space, runs `smart_sim.py` for every combination, and collects the results into a table. |
| `strategy_sweep.py` | The shared engine behind the 7-strategy comparison: `simulate_with_strategy()` runs any one of the 7 strategies through one common hourly loop, and `run_strategy_sweep()` goes through all 7 strategies x 3 locations x 4 forecast-error levels (84 runs). |

These files contain the **simulation logic** (who gets how much energy
each hour, and in what order). If you want to change the **rules** of
energy allocation (e.g. the priority order of electrolyzer/DAC/reactor),
look here -- the comments at the top of `baseline_sim.py` (and, for the
7-strategy version, `strategy_sweep.py`) describe in detail why it's
structured exactly this way, including a design mistake that was tried
and reverted.

### 5.5 `analysis/` -- figures and comparison

| File | What it does |
|---|---|
| `plots.py` | All the plotting functions in one place (not runnable on its own). If you want to change how a figure looks (color, size, layout), look here. |
| `compare.py` | Runs the baseline+smart simulation, finds the worst 7-day period, produces figures 1-2. |
| `sweep_analysis.py` | Reads `sweep_results_full.csv`, produces figures 3-4 (heatmap, robustness curve). |
| `strategy_comparison.py` | Reads `strategy_sweep_results.csv` and produces all 5 figures for the 7-strategy comparison (cold-start count by location, robustness, complexity vs. effectiveness, critical-period time series, uptime by location). |

---

## 6. Common tasks (recipes)

### 6.1 Adding a new location

1. Open `config.py`, find the `LOCATIONS` dictionary.
2. Add a new entry, e.g.:
   ```python
   "arizona": {
       "name": "Phoenix, Arizona",
       "latitude": 33.4484,
       "longitude": -112.0740,
       "altitude_m": 331,
       "timezone": "America/Phoenix",
       "weather_csv": DATA_DIR / "arizona_weather.csv",
   },
   ```
3. Download its data: `python data_fetch/pvgis_fetch.py --location arizona`
4. It's now usable everywhere: `python run_baseline.py --location arizona`

If you also want to include it in the sweep, add it to the
`SWEEP_LOCATIONS` list as well.

### 6.2 "What happens if I install a bigger BESS?"

```python
# in config.py:
BESS_CAPACITY_KWH = 3000   # instead of 2000
```

Then run: `python run_baseline.py --location sevilla` and
`python run_smart.py --location sevilla` -- you can compare the new
`coldstart_count` values against the earlier ones.

### 6.3 "Which (threshold, reserve) combination is best for a given location?"

Look at `results/sweep_results_full.csv`, or run:

```bash
python analysis/sweep_analysis.py
```

At the end of the output, it prints the best combination per location,
and also produces the heatmap figures (`results/fig3_heatmap_<location>.png`).

### 6.4 "I just want to quickly test one model, not the whole year"

Run the model's file on its own, e.g.:

```bash
python models/sabatier_model.py
```

This runs the built-in self-tests (see section 5.2), giving fast
feedback without having to run the full year.

### 6.5 "I broke something — how do I find out where the bug is?"

Work through the module hierarchy from the bottom up:
`models/` one by one -> `control/rtu_layer.py`, `control/controller.py`
-> `simulation/baseline_sim.py` -> `simulation/smart_sim.py`. At each
step, run the file on its own (where there's a self-test), so you can
narrow down at which level the error appears.

---

## 7. What NOT to modify (unless you know exactly why)

- `models/*.py` and `control/rtu_layer.py` -- these are the
  physical/safety models, and they're thoroughly tested. If you modify
  them, also re-run the built-in self-tests (`python models/<file>.py`)
  afterward.
- Section 9 of `config.py` (stoichiometric constants) -- these are
  physical constants (molar masses, heating value), not "tunable"
  parameters.
- Don't edit the `data/*.csv` files by hand -- if you need new data,
  download it again with `pvgis_fetch.py`.
