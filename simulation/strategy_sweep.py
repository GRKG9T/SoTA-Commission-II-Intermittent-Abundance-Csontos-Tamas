"""
simulation/strategy_sweep.py -- Shared simulation engine + comparison run of
the 7 strategies (84 = 7 strategies x 3 locations x 4 forecast_error)

This file does two things:
    1. simulate_with_strategy() -- a single, shared hourly simulation loop
       that any strategy (control/strategies/*.py) can execute. Only the
       strategy instance changes, everything else (PV/BESS/Sabatier/
       electrolyzer/DAC models, RTU layer) stays the same.
    2. run_strategy_sweep() -- goes through all 84 combinations.

Important -- dispatch logic: for every strategy (following the pattern of
the earlier, already-validated baseline_sim.py/smart_sim.py), the
electrolyzer+DAC may only use PV surplus, never the BESS. The reactor's
own maintenance, however, can always draw on the full BESS range (down to
min_soc).

An earlier version tried to also give the electrolyzer/DAC access to the
BESS, up to a "reserve threshold" that varied by strategy -- this failed
because the maintenance energy need of just one cold night
(~14 hours x 50 kW / 0.92 efficiency ~= 760 kWh) already exceeds the
entire reserve range under study (max. 40% = 800 kWh). In other words,
even a "perfectly" large reserve would only just barely survive a single
night, with no chance of multi-day protection -- and instead of a
300+ cold-starts/year difference between the 7 strategies, all of them
(except the two full-shutdown strategies) performed equally poorly.

The difference between the 7 strategies, then, is not in how much BESS
access they get (all of them are PV-only for the industrial loads), but
in when and based on what signal they completely cut off the
electrolyzer/DAC -- thereby leaving more PV surplus for charging the BESS,
before the shortage actually hits. See the individual strategy files
(control/strategies/*.py) for the exact signals (fixed SOC threshold,
forecast deficit, proportional SOC threshold, SOC threshold computed from
a physical formula, early "cloudy weather" signal, full trajectory
projection).
"""

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
from control.rtu_layer import RTULayer
from control.strategies import ALL_STRATEGIES
from models.bess_model import BESSModel
from models.dac_model import DACModel
from models.electrolyzer_model import ElectrolyzerModel
from models.pv_model import PVModel
from models.sabatier_model import SabatierModel
from simulation.baseline_sim import compute_metrics

# Which "reserve_fraction" each strategy uses, if it uses one at all
# (None = not used / calculated differently -- see the given strategy's
# file).
_STRATEGY_RESERVE_FRACTION = {
    "reactive_baseline": None,
    "fixed_reserve": config.FIXED_RESERVE_FRACTION,
    "forecast_binary": config.RESERVE_FRACTION,
    "proportional_reserve": None,  # uses min/max_reserve_fraction instead
    "temperature_based": None,  # calculated from a physical formula
    "precharge": config.RESERVE_FRACTION,
    "rolling_horizon": config.RESERVE_FRACTION,
}


def build_strategy(strategy_class, forecast_pv_kw):
    """
    Creates a strategy instance with the default values from config.py.
    We use the same call for every strategy -- each strategy only reads
    out the fields it needs (see control/strategies/base_strategy.py).
    """
    return strategy_class(
        bess_capacity_kwh=config.BESS_CAPACITY_KWH,
        bess_min_soc=config.BESS_MIN_SOC,
        bess_max_soc=config.BESS_MAX_SOC,
        maintenance_kw=config.SABATIER_MAINTENANCE_KW,
        coldstart_kw=config.SABATIER_COLDSTART_KW,
        tau_hours=config.SABATIER_TAU_HOURS,
        min_temp=config.SABATIER_MIN_TEMP_C,
        electrolyzer_min_kw=config.ELECTROLYZER_MIN_KW,
        pv_capacity_kw=config.PV_CAPACITY_KW,
        forecast_pv_kw=forecast_pv_kw,
        threshold_hours=config.THRESHOLD_HOURS,
        reserve_fraction=_STRATEGY_RESERVE_FRACTION.get(strategy_class.name),
        min_reserve_fraction=config.PROPORTIONAL_MIN_RESERVE_FRACTION,
        max_reserve_fraction=config.PROPORTIONAL_MAX_RESERVE_FRACTION,
        precharge_trigger_fraction=config.PRECHARGE_TRIGGER_FRACTION,
    )


def _build_forecast(pv_power: pd.Series, forecast_error_std: float, random_seed: int) -> np.ndarray:
    """Perfect forecast (forecast_error_std=0) or a version loaded with
    additive Gaussian noise -- see the identical logic in smart_sim.py."""
    if forecast_error_std > 0:
        rng = np.random.default_rng(random_seed)
        noise = rng.normal(loc=0.0, scale=forecast_error_std * config.PV_CAPACITY_KW, size=len(pv_power))
        return np.clip(pv_power.to_numpy() + noise, 0.0, None)
    return pv_power.to_numpy()


def simulate_with_strategy(
    weather_df: pd.DataFrame,
    location_key: str,
    strategy_class,
    forecast_error_std: float = 0.0,
    random_seed: int = None,
) -> pd.DataFrame:
    """
    Simulates one full year (8760 hours) with a given strategy.

    Returns a DataFrame with the same columns as
    simulate_baseline()/simulate_smart() -- so the existing
    compute_metrics() can be used unchanged.
    """
    random_seed = config.RANDOM_SEED if random_seed is None else random_seed
    loc = config.LOCATIONS[location_key]

    pv = PVModel(
        capacity_kw=config.PV_CAPACITY_KW,
        tilt=config.PV_TILT,
        azimuth=config.PV_AZIMUTH,
        efficiency=config.PV_EFFICIENCY,
        latitude=loc["latitude"],
        longitude=loc["longitude"],
        altitude=loc["altitude_m"],
        gamma_pdc=config.PV_GAMMA_PDC,
    )
    pv_power = pv.simulate(weather_df)

    bess = BESSModel(
        capacity_kwh=config.BESS_CAPACITY_KWH,
        max_charge_kw=config.BESS_MAX_CHARGE_KW,
        max_discharge_kw=config.BESS_MAX_DISCHARGE_KW,
        min_soc=config.BESS_MIN_SOC,
        max_soc=config.BESS_MAX_SOC,
        efficiency=config.BESS_EFFICIENCY,
    )
    reactor = SabatierModel(
        min_temp=config.SABATIER_MIN_TEMP_C,
        operating_temp=config.SABATIER_OPERATING_TEMP_C,
        tau_hours=config.SABATIER_TAU_HOURS,
        maintenance_kw=config.SABATIER_MAINTENANCE_KW,
        coldstart_kw=config.SABATIER_COLDSTART_KW,
        coldstart_hours=config.SABATIER_COLDSTART_HOURS,
    )
    electrolyzer = ElectrolyzerModel(
        min_kw=config.ELECTROLYZER_MIN_KW,
        max_kw=config.ELECTROLYZER_MAX_KW,
        kwh_per_kg_h2=config.ELECTROLYZER_KWH_PER_KG_H2,
    )
    dac = DACModel(
        power_kw=config.DAC_POWER_KW,
        ramp_hours=config.DAC_RAMP_HOURS,
        kwh_per_kg_co2=config.DAC_KWH_PER_KG_CO2,
    )
    rtu = RTULayer(
        bess_capacity_kwh=config.BESS_CAPACITY_KWH,
        bess_min_soc=config.BESS_MIN_SOC,
        bess_max_soc=config.BESS_MAX_SOC,
        bess_max_charge_kw=config.BESS_MAX_CHARGE_KW,
        bess_max_discharge_kw=config.BESS_MAX_DISCHARGE_KW,
        electrolyzer_max_kw=config.ELECTROLYZER_MAX_KW,
        dac_max_kw=config.DAC_POWER_KW,
    )

    forecast_pv_kw = _build_forecast(pv_power, forecast_error_std, random_seed)
    strategy = build_strategy(strategy_class, forecast_pv_kw)

    timestamps = pv_power.index
    pv_values = pv_power.to_numpy()
    env_temps = weather_df["T2m"].to_numpy()
    min_soc_kwh = bess.min_soc_kwh

    records = []

    for i in range(len(timestamps)):
        pv_kw = float(pv_values[i])
        env_temp_c = float(env_temps[i])

        bess_soc_kwh = bess.soc_kwh
        bess_discharge_available_kw = min(max(0.0, bess_soc_kwh - min_soc_kwh), bess.max_discharge_kw)
        total_available_kw = pv_kw + bess_discharge_available_kw

        decision = strategy.decide(
            current_hour=i,
            system_state={
                "pv_power_kw": pv_kw,
                "env_temp_c": env_temp_c,
                "reactor_state": reactor.state,
                "reactor_temperature_c": reactor.temperature_c,
                "bess_soc_kwh": bess_soc_kwh,
                "bess_discharge_available_kw": bess_discharge_available_kw,
                "total_available_kw": total_available_kw,
            },
        )

        reactor_command = decision["reactor_command"]
        reactor_reserved_kw = decision["reactor_reserved_kw"]
        reserve_kwh = max(0.0, decision["reserve_kwh"])

        # --- Dispatch: PV-only for the industrial loads, for every
        # strategy (see the module docstring -- this is the project's
        # earlier, validated mechanism; an earlier version tried to also
        # give the industrial loads partial access to the BESS via a
        # reserve threshold, but it turned out that already the
        # maintenance energy need of a single cold night (~760 kWh)
        # exceeds the entire reserve range under study (max. 40% =
        # 800 kWh) -- meaning even a "perfectly" tuned reserve would
        # barely survive a single night, with no chance of multi-day
        # protection. The difference between the strategies is therefore
        # not in how much BESS access they get, but in when and based on
        # what signal they completely cut off the industrial loads (see
        # the individual strategy files).
        pv_remaining_kw = max(0.0, pv_kw - reactor_reserved_kw)
        industrial_budget_kw = pv_remaining_kw

        dac_target_kw = min(industrial_budget_kw, config.DAC_POWER_KW) if decision["dac_command"] == "on" else 0.0
        remaining_kw = industrial_budget_kw - dac_target_kw
        electrolyzer_target_kw = (
            min(remaining_kw, config.ELECTROLYZER_MAX_KW) if decision["electrolyzer_command"] == "on" else 0.0
        )

        electrolyzer_command = "on" if electrolyzer_target_kw > 0 else "off"
        dac_command = "on" if dac_target_kw > 0 else "off"

        ely_result = electrolyzer.step(available_power_kw=electrolyzer_target_kw, command=electrolyzer_command)
        dac_result = dac.step(available_power_kw=dac_target_kw, command=dac_command)
        reactor_result = reactor.step(
            available_power_kw=reactor_reserved_kw, env_temp_c=env_temp_c, command=reactor_command
        )

        total_consumption_kw = (
            ely_result["power_consumed_kw"] + dac_result["power_consumed_kw"] + reactor_result["power_consumed_kw"]
        )
        net_balance_kw = pv_kw - total_consumption_kw

        # The RTU arbitrates the same way for every strategy -- the
        # limits do not change by strategy. (The reserve was already
        # accounted for at dispatch time, which is why reserve_kwh=0
        # here -- see the explanation at the top of the module about why
        # the same reserve cannot be enforced a second time at the RTU
        # level, without also blocking the reactor's own need.)
        approved = rtu.arbitrate(
            {"bess_power_kw": net_balance_kw, "reserve_kwh": 0.0},
            {"bess_soc_kwh": bess.soc_kwh},
        )
        bess_result = bess.step(power_kw=approved["bess_power_kw"], reserve_kwh=0.0)

        records.append(
            {
                "timestamp": timestamps[i],
                "pv_power_kw": pv_kw,
                "bess_soc_kwh": bess_result["soc_kwh"],
                "bess_soc_fraction": bess.soc_fraction,
                "bess_curtailed_kw": bess_result["curtailed_kw"],
                "reactor_state": reactor_result["state"].value,
                "reactor_temperature_c": reactor_result["temperature_c"],
                "reactor_coldstart_triggered": reactor_result["coldstart_triggered"],
                "reactor_power_kw": reactor_result["power_consumed_kw"],
                "electrolyzer_power_kw": ely_result["power_consumed_kw"],
                "electrolyzer_h2_kg": ely_result["h2_produced_kg"],
                "dac_power_kw": dac_result["power_consumed_kw"],
                "dac_co2_kg": dac_result["co2_captured_kg"],
                "reserve_active": decision["life_insurance_active"],
                "reserve_kwh": reserve_kwh,
            }
        )

    return pd.DataFrame(records).set_index("timestamp")


def run_strategy_sweep(verbose: bool = True) -> pd.DataFrame:
    """
    Runs all 7 strategies x 3 locations x 4 forecast_error levels
    (7 x 3 x 4 = 84 full-year simulations), and collects the results.
    """
    locations = config.SWEEP_LOCATIONS
    forecast_errors = config.SWEEP_FORECAST_ERROR_STD

    total = len(ALL_STRATEGIES) * len(locations) * len(forecast_errors)
    count = 0
    start_time = time.time()

    weather_cache = {}
    records = []

    for location_key in locations:
        if location_key not in weather_cache:
            weather_cache[location_key] = pd.read_csv(
                config.LOCATIONS[location_key]["weather_csv"], index_col=0, parse_dates=True
            )
        weather = weather_cache[location_key]

        for fe_index, forecast_error in enumerate(forecast_errors):
            random_seed = config.RANDOM_SEED + locations.index(location_key) * 100 + fe_index

            for strategy_class in ALL_STRATEGIES:
                count += 1
                result = simulate_with_strategy(
                    weather, location_key, strategy_class, forecast_error_std=forecast_error, random_seed=random_seed
                )
                metrics = compute_metrics(result)
                records.append(
                    {
                        "strategy": strategy_class.name,
                        "strategy_display_name": strategy_class.display_name,
                        "complexity": config.STRATEGY_COMPLEXITY[strategy_class.name],
                        "location": location_key,
                        "forecast_error_std": forecast_error,
                        **metrics,
                    }
                )
                if verbose:
                    elapsed = time.time() - start_time
                    print(
                        f"[{count}/{total}] {location_key:<8} fe={forecast_error:.1f} "
                        f"{strategy_class.display_name:<26} -> coldstart={metrics['coldstart_count']:>4}  "
                        f"({elapsed:.0f} s elapsed)"
                    )

    return pd.DataFrame(records)


def main() -> None:
    print("Strategy comparison sweep: 7 strategies x 3 locations x 4 forecast_error = 84 runs\n")

    t0 = time.time()
    results_df = run_strategy_sweep()
    elapsed = time.time() - t0
    print(f"\nSweep done: {len(results_df)} runs, in {elapsed:.0f} seconds.")

    out_csv = config.STRATEGY_RESULTS_DIR / "strategy_sweep_results.csv"
    results_df.to_csv(out_csv, index=False)
    print(f"Results saved: {out_csv}")


if __name__ == "__main__":
    main()
