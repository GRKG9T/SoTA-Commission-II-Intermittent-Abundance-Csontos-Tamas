"""
config.py -- Global parameters and constants

This file contains all the numeric values for the entire simulation in one place.
The goal: the other modules (pv_model.py, bess_model.py, etc.) should not
contain any "magic numbers" anywhere -- everything should be imported from here, e.g.:

    from config import PV_CAPACITY_KW, BESS_CAPACITY_KWH

If you want to change a parameter (e.g. simulate a bigger BESS), you only
need to edit this file -- the rest of the code stays unchanged, because it
references names imported from here everywhere, not hardcoded numbers.
"""

from pathlib import Path

# =============================================================================
# 0. Directory structure
# =============================================================================
# Path(__file__)          -> the path to this config.py file
# .resolve()               -> converts it to an absolute path (e.g. "C:\Users\...\config.py")
# .parent                  -> the folder containing the file -> this is the project root
#
# This way, no matter where you run the scripts from (e.g. "python run_baseline.py" or
# "python simulation\baseline_sim.py"), the paths will always correctly
# point to the data/ and results/ folders.
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
RESULTS_DIR = BASE_DIR / "results"

# We make sure these folders exist when config is imported.
# exist_ok=True -> does not raise an error if the folder already exists.
DATA_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


# =============================================================================
# 1. Locations
# =============================================================================
# The project compares three climatically different locations to show
# that the optimal life insurance threshold is location-dependent.
#
#   sevilla  -> Mediterranean climate, lots of sunshine, rare but existing
#               overcast periods -> "medium" test case
#   morocco  -> desert climate (Ouarzazate -- the site of the real Noor
#               solar energy complex), very stable, few overcast days ->
#               a low threshold is expected to be sufficient here
#   scotland -> humid, oceanic climate (Edinburgh), frequent multi-day
#               overcast periods -> the most "life insurance" events are
#               expected here, and getting the threshold right matters
#               most here
#
# The "weather_csv" field shows where data_fetch/pvgis_fetch.py saves the
# downloaded PVGIS TMY data, and where pv_model.py reads it from.
LOCATIONS = {
    "sevilla": {
        "name": "Seville, Spain",
        "latitude": 37.3891,
        "longitude": -5.9845,
        "altitude_m": 11,
        "timezone": "Europe/Madrid",
        "weather_csv": DATA_DIR / "sevilla_weather.csv",
    },
    "morocco": {
        "name": "Ouarzazate, Morocco",
        "latitude": 30.9335,
        "longitude": -6.9370,
        "altitude_m": 1160,
        "timezone": "Africa/Casablanca",
        "weather_csv": DATA_DIR / "morocco_weather.csv",
    },
    "scotland": {
        "name": "Edinburgh, Scotland",
        "latitude": 55.9533,
        "longitude": -3.1883,
        "altitude_m": 47,
        "timezone": "Europe/London",
        "weather_csv": DATA_DIR / "scotland_weather.csv",
    },
}


# =============================================================================
# 2. PV plant parameters
# =============================================================================
PV_CAPACITY_KW = 1000   # nominal DC peak power [kW]
PV_TILT = 30             # panel tilt angle [degrees] (0 = horizontal)
PV_AZIMUTH = 180         # orientation [degrees] (180 = south -- optimal in the northern hemisphere)
PV_EFFICIENCY = 0.96     # inverter (DC -> AC) efficiency

# Temperature power coefficient [1/C]: for every degree of warming, the
# panel's power output drops by this percentage relative to its nominal
# value (measured at 25 C). -0.004 is a typical, literature value for
# crystalline silicon panels -- this is what pvlib's PVWatts DC model
# uses ("gamma_pdc").
PV_GAMMA_PDC = -0.004


# =============================================================================
# 3. BESS (battery energy storage system) parameters
# =============================================================================
BESS_CAPACITY_KWH = 2000  # nominal energy capacity [kWh]

# The charge/discharge power is derived from the "C-rate": 0.5C means
# the battery could fully charge/discharge in 2 hours -- this is a
# typical value for a grid-scale BESS, and it also matches the PV plant's
# 1000 kW peak power (so the BESS is able to absorb the entire PV
# surplus from a single hour).
BESS_MAX_CHARGE_KW = 1000
BESS_MAX_DISCHARGE_KW = 1000

BESS_MIN_SOC = 0.10        # minimum state of charge [0-1] -- cannot discharge below this
BESS_MAX_SOC = 0.95        # maximum state of charge [0-1] -- cannot charge above this
BESS_EFFICIENCY = 0.92     # round-trip efficiency, simplified

# Below this state-of-charge level, a moment counts as a "deep discharge"
# in the "bess_deep_discharge" metric in chapter 6.
DEEP_DISCHARGE_THRESHOLD = 0.15


# =============================================================================
# 4. Sabatier reactor parameters (the project's most critical model)
# =============================================================================
SABATIER_MIN_TEMP_C = 300         # below this the reactor already counts as "cold"
SABATIER_OPERATING_TEMP_C = 400   # normal operating (producing) temperature
SABATIER_TAU_HOURS = 6.0          # cooling time constant [hours] in Newton's law of cooling

SABATIER_MAINTENANCE_KW = 50      # maintenance heating power (not producing, but stays warm)
SABATIER_COLDSTART_KW = 200       # cold start power demand
SABATIER_COLDSTART_HOURS = 6.0    # cold start duration -- this is the 4-6 hour loss we want to avoid


# =============================================================================
# 5. Electrolyzer parameters
# =============================================================================
# The documentation does not give a concrete example value for these, so
# I used my own, justified assumption: a typical PEM electrolyzer can
# turn down to about 10% (turndown). The max power is deliberately sized
# around the PV plant's average (not peak) output (~300 kW, versus the
# 1000 kW peak capacity): this way it mostly makes use of the available
# solar energy, but during the sunniest hours PV surplus remains
# available to charge the BESS as well -- this makes physical sense: if
# the electrolyzer+DAC together tied up nearly the entire PV peak, the
# BESS could never charge, and it could not fulfill its
# reactor-protection ("life insurance") role either.
ELECTROLYZER_MIN_KW = 30    # minimum load (10% turndown)
ELECTROLYZER_MAX_KW = 300   # maximum load

# Specific energy demand [kWh / kg H2]: how much electrical energy is
# needed to produce 1 kg of hydrogen. The theoretical minimum is about
# 39.4 kWh/kg (based on the lower heating value) -- real, currently
# operating PEM/alkaline electrolyzers use more than this, typically
# 50-55 kWh/kg, due to losses.
ELECTROLYZER_KWH_PER_KG_H2 = 55


# =============================================================================
# 6. DAC (direct air capture of CO2) parameters
# =============================================================================
# My own, justified assumption: for a small, remote plant, a modestly
# sized DAC unit is enough to cover the Sabatier reactor's CO2 demand --
# see also the note in the electrolyzer section about why we deliberately
# stay below the PV peak.
DAC_POWER_KW = 80        # nominal (constant) consumption during operation
DAC_RAMP_HOURS = 0.5     # ramp-up/ramp-down time [hours]

# Specific energy demand [kWh / kg CO2]: how much energy is needed to
# extract 1 kg of CO2 from the air. Literature value (including the
# thermal energy equivalent, about 2000 kWh/tonne CO2 -- typical for
# direct air capture).
DAC_KWH_PER_KG_CO2 = 2.0


# =============================================================================
# 7. Life insurance controller parameters
# =============================================================================
# These are the default values for a single run (e.g. run_smart.py runs
# with these by default if you don't pass the --threshold / --reserve
# command-line options). The actual optimal values will be shown by the
# parameter sweep (step 9) -- this is just an initial, reasonable choice.
THRESHOLD_HOURS = 24      # life insurance mode activates above this many hours of forecast deficit
RESERVE_FRACTION = 0.25   # this fraction of the BESS capacity may be reserved

# The Open-Meteo API provides a forecast of at most 7 days (168 hours) --
# this is the maximum window the controller can use for the deficit
# calculation.
FORECAST_HORIZON_HOURS = 168


# =============================================================================
# 8. Parameter sweep values (step 9)
# =============================================================================
# Values per section 5.4 of the documentation. Their product gives the
# 360 simulation runs: 5 x 6 x 4 x 3 = 360.
SWEEP_THRESHOLD_HOURS = [12, 24, 36, 48, 72]
SWEEP_RESERVE_FRACTION = [0.10, 0.15, 0.20, 0.25, 0.30, 0.40]
SWEEP_FORECAST_ERROR_STD = [0.0, 0.1, 0.2, 0.4]
SWEEP_LOCATIONS = list(LOCATIONS.keys())

# Fixed random number generator seed, so the simulation of the forecast
# error (Gaussian noise) always gives the same result -- this way the
# runs remain reproducible and comparable.
RANDOM_SEED = 42


# =============================================================================
# 9. Sabatier reaction stoichiometry (for the methane_output_kwh metric)
# =============================================================================
# The Sabatier model (models/sabatier_model.py) only calculates the
# reactor's temperature -- the actual material flow (H2 -> CH4) is
# estimated in the simulation (simulation/) layer, using this
# stoichiometry:
#   CO2 + 4 H2 -> CH4 + 2 H2O
# 4 mol of H2 becomes 1 mol of CH4. Given the project's electrolyzer/DAC
# sizing (300 kW electrolyzer vs. 80 kW DAC), H2 is the bottleneck
# (limiting reagent), CO2 is always in surplus -- so the methane output
# is simply calculated from H2 production, without a CO2 constraint.
CH4_MOLAR_MASS_G = 16.04    # molar mass of methane [g/mol]
H2_MOLAR_MASS_G = 2.016     # molar mass of hydrogen [g/mol]
CH4_LHV_KWH_PER_KG = 13.9   # lower heating value of methane [kWh/kg] (literature value)


# =============================================================================
# 10. Strategy comparison parameters (control/strategies/)
# =============================================================================
# Each strategy runs with its own, reasonable default parameters in the
# 7-strategy comparison (not a full sweep grid over threshold/reserve
# values -- that was already done in step 9 for a single strategy; here
# we compare the strategies themselves, each with one well-chosen
# setting).

# 2. Fixed reserve: a constant BESS fraction for the reactor, independent of weather.
FIXED_RESERVE_FRACTION = 0.20

# 4. Proportional reserve: the reserve scales linearly between these two
# values according to the severity of the expected deficit (0% severity -> min, 100% -> max).
PROPORTIONAL_MIN_RESERVE_FRACTION = 0.10
PROPORTIONAL_MAX_RESERVE_FRACTION = 0.40

# 6. Precharge strategy: if the forecast average PV output (over the next
# threshold_hours hours, counting nighttime as well) falls below this
# fraction of the nominal capacity, it proactively starts charging
# (shuts down the electrolyzer/DAC), before any formal deficit can be
# calculated. Note: since a 24+ hour average always includes
# nighttime (0 kW), a "seemingly reasonable" 40% threshold would in
# practice almost always be met (even on a completely clear day the
# 24-hour average is only around 20-30%) -- so this threshold was
# calibrated much lower based on the actual data distribution: around
# 12% already clearly indicates a period worse than average (about 22%),
# not just an ordinary day.
PRECHARGE_TRIGGER_FRACTION = 0.12

# Complexity rating (1-5, assigned manually) -- a subjective but justified
# estimate of how much "thinking"/computation is required to understand
# and implement the given strategy compared to the simplest one (1):
#   1: no forecast, no state-dependent calculation
#   2: a single forecast sum compared to a threshold
#   3: the above + an additional decision branch (proportional or trigger calculation)
#   4: physical formula (logarithm, temperature-dependent)
#   5: projecting the trajectory across the entire forecast window,
#      recalculated every hour
STRATEGY_COMPLEXITY = {
    "reactive_baseline": 1,
    "fixed_reserve": 1,
    "forecast_binary": 2,
    "proportional_reserve": 3,
    "temperature_based": 4,
    "precharge": 3,
    "rolling_horizon": 5,
}

# The strategy comparison's own output folder.
STRATEGY_RESULTS_DIR = RESULTS_DIR / "strategy_comparison"
STRATEGY_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
