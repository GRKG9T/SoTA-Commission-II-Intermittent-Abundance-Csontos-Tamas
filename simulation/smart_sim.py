"""
simulation/smart_sim.py -- Simulation run with the proactive ("life insurance") controller

The same infrastructure (PV, BESS, Sabatier, electrolyzer, DAC, RTU) as in
baseline_sim.py -- only the controller is different: instead of the naive,
reactive decisions, the LifeInsuranceController built in
control/controller.py decides every hour, based on a forecast.

The single structural difference between the two simulations (at the code
level too): here, at the start of every hour we call controller.decide(),
and use its response for the electrolyzer/DAC/reactor commands, instead of
computing them reactively from the current hour's actual PV.

By default we use a "perfect" (zero-error) forecast -- forecast_pv_kw is
simply the already-known (actual) PV time series. simulate_smart()'s
optional forecast_error_std parameter can add additive Gaussian noise
(see config.py section 9.1) -- this is used by step 9 (sweep_sim.py) for
the robustness investigation.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
from control.controller import LifeInsuranceController
from control.rtu_layer import RTULayer
from models.bess_model import BESSModel
from models.dac_model import DACModel
from models.electrolyzer_model import ElectrolyzerModel
from models.pv_model import PVModel
from models.sabatier_model import ReactorState, SabatierModel
from simulation.baseline_sim import compute_metrics, simulate_baseline


def simulate_smart(
    weather_df: pd.DataFrame,
    location_key: str,
    threshold_hours: int = None,
    reserve_fraction: float = None,
    forecast_error_std: float = 0.0,
    random_seed: int = None,
) -> pd.DataFrame:
    """
    Simulates one full year with the proactive (life insurance) controller.

    weather_df:         the location's PVGIS TMY weather data.
    location_key:        one of the keys of the config.LOCATIONS dict.
    threshold_hours:     optional override (default: config.THRESHOLD_HOURS)
    reserve_fraction:    optional override (default: config.RESERVE_FRACTION)
    forecast_error_std:  the standard deviation of the forecast error, as a
                          fraction of PV_CAPACITY_KW [0-1] (0.0 = "perfect"
                          forecast). See section 9.1: additive Gaussian
                          noise model.
    random_seed:         random number generator seed for reproducible
                          noise generation (default: config.RANDOM_SEED).

    Returns a DataFrame with the same columns as simulate_baseline() -- so
    the same compute_metrics() function can be used on both results.
    """
    threshold_hours = config.THRESHOLD_HOURS if threshold_hours is None else threshold_hours
    reserve_fraction = config.RESERVE_FRACTION if reserve_fraction is None else reserve_fraction
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
    # The forecast = the actual (already known) PV series + optional
    # additive Gaussian noise (see config.py section 9.1 -- real forecast
    # error is neither symmetric nor time-correlated, but for a basic
    # robustness investigation this simplification is sufficient). The
    # noise's standard deviation is proportional to the PV plant's rated
    # capacity, and we never let the PV fall below 0.
    if forecast_error_std > 0:
        rng = np.random.default_rng(random_seed)
        noise = rng.normal(loc=0.0, scale=forecast_error_std * config.PV_CAPACITY_KW, size=len(pv_power))
        forecast_pv_kw = np.clip(pv_power.to_numpy() + noise, 0.0, None)
    else:
        forecast_pv_kw = pv_power.to_numpy()  # "perfect" forecast

    controller = LifeInsuranceController(
        threshold_hours=threshold_hours,
        reserve_fraction=reserve_fraction,
        forecast_pv_kw=forecast_pv_kw,
        bess_capacity_kwh=config.BESS_CAPACITY_KWH,
        bess_min_soc=config.BESS_MIN_SOC,
        bess_max_soc=config.BESS_MAX_SOC,
        maintenance_kw=config.SABATIER_MAINTENANCE_KW,
        coldstart_kw=config.SABATIER_COLDSTART_KW,
        tau_hours=config.SABATIER_TAU_HOURS,
        electrolyzer_min_kw=config.ELECTROLYZER_MIN_KW,
    )

    timestamps = pv_power.index
    pv_values = pv_power.to_numpy()
    env_temps = weather_df["T2m"].to_numpy()

    records = []

    for i in range(len(timestamps)):
        pv_kw = float(pv_values[i])
        env_temp_c = float(env_temps[i])

        bess_discharge_available_kw = min(bess.get_available_kwh(0.0), bess.max_discharge_kw)
        total_available_kw = pv_kw + bess_discharge_available_kw

        decision = controller.decide(
            current_hour=i,
            system_state={
                "pv_power_kw": pv_kw,
                "reactor_state": reactor.state,
                "bess_soc_kwh": bess.soc_kwh,
                "bess_discharge_available_kw": bess_discharge_available_kw,
            },
        )

        reactor_command = decision["reactor_command"]
        if reactor_command == "operate":
            reactor_reserved_kw = 0.0 if reactor.state in (ReactorState.OPERATING, ReactorState.MAINTENANCE) else config.SABATIER_COLDSTART_KW
        elif reactor_command == "maintain":
            reactor_reserved_kw = config.SABATIER_MAINTENANCE_KW
        else:  # shutdown
            reactor_reserved_kw = total_available_kw

        # The electrolyzer and the DAC (if the controller allows them at
        # all this hour) may only use PV surplus -- they never drain the
        # BESS, exactly like in the baseline.
        pv_surplus_kw = max(0.0, pv_kw - reactor_reserved_kw)
        dac_target_kw = min(pv_surplus_kw, config.DAC_POWER_KW) if decision["dac_command"] == "on" else 0.0
        remaining_pv_surplus_kw = pv_surplus_kw - dac_target_kw
        electrolyzer_target_kw = (
            min(remaining_pv_surplus_kw, config.ELECTROLYZER_MAX_KW) if decision["electrolyzer_command"] == "on" else 0.0
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

        # Important: reserve_kwh is not passed to the RTU/BESS to limit
        # net_balance_kw. The RTU's reserve-locking exists to keep other
        # consumers away from the reserved capacity -- but for us the
        # electrolyzer and the DAC never drain the BESS anyway (they only
        # use PV surplus), so there is no one to protect the reserve
        # from. If we passed it through anyway, the RTU would also limit
        # the reactor's own maintenance need against the reserve -- which
        # is exactly what we wanted the reserve to prevent! reserve_kwh
        # is therefore only used here for logging/metrics
        # (reserve_active_hours).
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
            }
        )

    return pd.DataFrame(records).set_index("timestamp")


# =============================================================================
# Standalone run: verification of step 8 per the documentation
#   "Check: fewer cold starts than the baseline -- if not, there is a
#    bug in the logic"
# =============================================================================
def main(location: str = "sevilla", threshold_hours: int = None, reserve_fraction: float = None) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    LOCATION = location
    threshold_hours = config.THRESHOLD_HOURS if threshold_hours is None else threshold_hours
    reserve_fraction = config.RESERVE_FRACTION if reserve_fraction is None else reserve_fraction

    print(f"Proactive (life insurance) simulation -- {config.LOCATIONS[LOCATION]['name']}")
    print(f"threshold_hours={threshold_hours}, reserve_fraction={reserve_fraction}\n")

    weather = pd.read_csv(config.LOCATIONS[LOCATION]["weather_csv"], index_col=0, parse_dates=True)

    print("Running baseline (naive) simulation for comparison...")
    baseline_result = simulate_baseline(weather, LOCATION)
    baseline_metrics = compute_metrics(baseline_result)

    print("Running proactive simulation...")
    smart_result = simulate_smart(weather, LOCATION, threshold_hours=threshold_hours, reserve_fraction=reserve_fraction)
    smart_metrics = compute_metrics(smart_result)

    out_csv = config.RESULTS_DIR / f"smart_{LOCATION}_hourly.csv"
    smart_result.to_csv(out_csv)
    print(f"\nHourly results saved: {out_csv}\n")

    print(f"{'Metric':<28}{'Baseline':>14}{'Proactive':>14}{'Improvement':>12}")
    print("-" * 68)
    for key, label, unit in [
        ("coldstart_count", "coldstart_count", "count/yr"),
        ("lost_production_hours", "lost_production_hours", "hours/yr"),
        ("methane_output_kwh", "methane_output_kwh", "kWh/yr"),
        ("bess_deep_discharge", "bess_deep_discharge", "count/yr"),
        ("curtailed_kwh", "curtailed_kwh", "kWh/yr"),
        ("reactor_warm_fraction_pct", "reactor_warm_fraction", "%"),
        ("reserve_active_hours", "reserve_active_hours", "hours/yr"),
    ]:
        b = baseline_metrics[key]
        s = smart_metrics[key]
        if key in ("coldstart_count", "lost_production_hours", "bess_deep_discharge", "curtailed_kwh"):
            improvement = f"{(1 - s / b) * 100:+.0f}%" if b else "n/a"
        else:
            improvement = f"{(s / b - 1) * 100:+.0f}%" if b else "n/a"
        print(f"{label:<28}{b:>10,.0f} {unit:<4}{s:>10,.0f} {unit:<4}{improvement:>8}")

    coldstart_baseline = baseline_metrics["coldstart_count"]
    coldstart_smart = smart_metrics["coldstart_count"]
    print()
    if coldstart_smart < coldstart_baseline:
        print(
            f"CHECK OK: the proactive controller resulted in fewer cold starts "
            f"({coldstart_smart} < {coldstart_baseline})."
        )
    else:
        print(
            f"WARNING: the proactive controller did not result in fewer cold starts "
            f"({coldstart_smart} >= {coldstart_baseline}) -- there is a bug in the logic!"
        )

    # --- Comparison chart: reactor temperature, baseline vs. proactive ---
    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True, sharey=True)

    axes[0].plot(baseline_result.index, baseline_result["reactor_temperature_c"], color="#dc2626", linewidth=0.6)
    axes[0].axhline(config.SABATIER_MIN_TEMP_C, color="#78716c", linestyle="--", linewidth=1)
    axes[0].set_title(f"Baseline (naive) -- {coldstart_baseline} cold starts")
    axes[0].set_ylabel("C")
    axes[0].grid(alpha=0.3)

    axes[1].plot(smart_result.index, smart_result["reactor_temperature_c"], color="#16a34a", linewidth=0.6)
    axes[1].axhline(config.SABATIER_MIN_TEMP_C, color="#78716c", linestyle="--", linewidth=1, label="min_temp")
    axes[1].set_title(f"Proactive (life insurance) -- {coldstart_smart} cold starts")
    axes[1].set_ylabel("C")
    axes[1].legend(loc="lower right")
    axes[1].grid(alpha=0.3)

    fig.tight_layout()
    out_png = config.RESULTS_DIR / f"smart_vs_baseline_{LOCATION}.png"
    fig.savefig(out_png, dpi=120)
    print(f"\nComparison chart saved: {out_png}")


if __name__ == "__main__":
    main()
