"""
simulation/baseline_sim.py -- "Naive" (baseline) controller reference simulation

This is the first place where all the models built so far (PV, BESS,
Sabatier, electrolyzer, DAC, RTU) are wired together into a single,
full-year (8760-hour) simulation. Using the "naive" controller from
documentation section 5.2: no weather forecast, no proactive reserve
reservation -- only reactive, same-day decisions. This will be the
baseline for comparison against the proactive "life insurance" controller
to be built later (step 8).

The naive control logic (documentation 5.2):
    "If there is PV surplus -> BESS charges
     If there isn't enough energy -> shed loads in order: electrolyzer -> DAC -> reactor
     If the BESS is critically low -> everything stops, reactor cools down"

We implement this on an hourly basis using a simple priority order: every
hour we calculate how much energy is available in total (PV production +
whatever the BESS could still discharge), and from this "budget" we
first try to cover the reactor's need (this is the most important thing
to protect), second the DAC, third (last, i.e. first to be dropped in a
shortage) the electrolyzer. This naturally produces the "shutdown order:
electrolyzer -> DAC -> reactor".

Important design decision -- two pitfalls that had to be eliminated along
the way:

1) The electrolyzer and the DAC may only use PV surplus, they never drain
   the BESS -- not even in the naive controller. If this were not the
   case (if either could freely drain the BESS too), then during a
   typical night the high-power industrial loads (up to 750 kW combined)
   would drain a 2000 kWh BESS within minutes/hours, and the reactor
   would cool down every night -- turning a "rare, multi-day
   bad weather" event into an everyday one, which does not match the
   project's basic assumption.

2) The question "is there enough energy to keep the reactor in
   production" is always decided from the actual PV (not from the
   hypothetical PV+BESS sum). If we also counted the BESS's hypothetical
   availability, a self-reinforcing loop would form: the reactor is free
   in "operate" state, so it never drains the BESS, so the BESS always
   stays full, so there would always "still be" hypothetical BESS
   capacity for maintenance, so the reactor would never cool down --
   not even during completely overcast, PV-less periods. That is why the
   "is there enough PV for production" (can_produce) variable looks
   exclusively at the actual pv_kw value.

With this, the reactor's state develops as follows:
    - During the day, if there is enough PV (>= the electrolyzer's
      minimum load): "operate" -- produces, free of charge.
    - At night (or on very overcast days): "maintain" -- cheap
      (maintenance_kw) maintenance covered from the BESS. This is the
      everyday, harmless cycle, and does not count as a cold start.
    - It only falls into COLD state (requiring a real cold start
      afterwards) if even maintenance (50 kW) cannot be covered -- this
      only happens during multi-day, PV-less/BESS-depleting periods,
      exactly as the project's main claim assumes.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
from control.rtu_layer import RTULayer
from models.bess_model import BESSModel
from models.dac_model import DACModel
from models.electrolyzer_model import ElectrolyzerModel
from models.pv_model import PVModel
from models.sabatier_model import ReactorState, SabatierModel


def simulate_baseline(weather_df: pd.DataFrame, location_key: str) -> pd.DataFrame:
    """
    Simulates one full year (the number of hours matching the length of
    weather_df, typically 8760) with the naive (baseline) controller.

    weather_df:   the location's PVGIS TMY weather data (read from the
                  CSV saved by pvgis_fetch.py, with a datetime index).
    location_key: one of the keys of the config.LOCATIONS dict (e.g. "sevilla").

    Returns a DataFrame with hourly rows and the key state/power columns
    -- from this, the metrics in chapter 6 can be calculated
    (see compute_metrics()).
    """
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

    timestamps = pv_power.index
    pv_values = pv_power.to_numpy()
    env_temps = weather_df["T2m"].to_numpy()

    records = []

    for i in range(len(timestamps)):
        pv_kw = float(pv_values[i])
        env_temp_c = float(env_temps[i])

        bess_discharge_available_kw = min(bess.get_available_kwh(0.0), bess.max_discharge_kw)
        total_available_kw = pv_kw + bess_discharge_available_kw

        # --- Naive, reactive, but state-dependent priority decision about the reactor ---
        # Important: the question "is there enough PV for production" is
        # always decided from the actual PV (not from the hypothetical
        # PV+BESS sum) -- this avoids the mistake where the BESS's
        # never-used, and therefore always "full", availability would
        # keep making operation "free" forever, even during periods with
        # no sun at all.
        can_produce = pv_kw >= config.ELECTROLYZER_MIN_KW

        if reactor.state in (ReactorState.OPERATING, ReactorState.MAINTENANCE):
            if can_produce:
                # There is enough PV for the feedstock supply -- stays in
                # production mode (or returns to it, if it was just being
                # maintained).
                reactor_command = "operate"
                reactor_reserved_kw = 0.0
            elif total_available_kw >= config.SABATIER_MAINTENANCE_KW:
                # Not enough PV for production (e.g. at night), but
                # maintenance (even from the BESS) can still be covered --
                # this is the everyday, harmless nighttime cycle.
                reactor_command = "maintain"
                reactor_reserved_kw = config.SABATIER_MAINTENANCE_KW
            else:
                # Not even maintenance can be covered -- this only happens
                # if the BESS is also depleted (e.g. after a multi-day
                # overcast period).
                reactor_command = "shutdown"
                reactor_reserved_kw = total_available_kw
        else:
            # COLD or COLD_START -- a (new or continuing) cold start needs
            # the full coldstart_kw.
            if total_available_kw >= config.SABATIER_COLDSTART_KW:
                reactor_command = "operate"
                reactor_reserved_kw = config.SABATIER_COLDSTART_KW
            elif total_available_kw >= config.SABATIER_MAINTENANCE_KW:
                reactor_command = "maintain"
                reactor_reserved_kw = config.SABATIER_MAINTENANCE_KW
            else:
                reactor_command = "shutdown"
                reactor_reserved_kw = total_available_kw

        # The electrolyzer and the DAC may only use PV surplus, they never
        # drain the BESS -- even in the naive controller, the BESS is
        # primarily kept in reserve to protect the reactor (in line with
        # section 5.2's basic rule "if there is PV surplus -> BESS
        # charges": in the absence of surplus, the industrial loads simply
        # get no energy, rather than having it topped up from the BESS).
        pv_surplus_kw = max(0.0, pv_kw - reactor_reserved_kw)
        dac_target_kw = min(pv_surplus_kw, config.DAC_POWER_KW)
        remaining_pv_surplus_kw = pv_surplus_kw - dac_target_kw
        electrolyzer_target_kw = min(remaining_pv_surplus_kw, config.ELECTROLYZER_MAX_KW)

        electrolyzer_command = "on" if electrolyzer_target_kw > 0 else "off"
        dac_command = "on" if dac_target_kw > 0 else "off"

        # --- Subsystems execute the commands ---
        ely_result = electrolyzer.step(available_power_kw=electrolyzer_target_kw, command=electrolyzer_command)
        dac_result = dac.step(available_power_kw=dac_target_kw, command=dac_command)
        reactor_result = reactor.step(
            available_power_kw=reactor_reserved_kw, env_temp_c=env_temp_c, command=reactor_command
        )

        total_consumption_kw = (
            ely_result["power_consumed_kw"] + dac_result["power_consumed_kw"] + reactor_result["power_consumed_kw"]
        )
        net_balance_kw = pv_kw - total_consumption_kw  # positive = BESS charges, negative = BESS covers the shortfall

        # The baseline never reserves a reserve -- this is the most
        # important difference compared to the later proactive (life
        # insurance) controller.
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
                "reserve_active": False,  # baseline: never active
            }
        )

    return pd.DataFrame(records).set_index("timestamp")


def compute_metrics(result_df: pd.DataFrame) -> dict:
    """
    Calculates the annual metrics per documentation chapter 6, from an
    hourly DataFrame returned by simulate_baseline() (or later
    smart_sim.py).
    """
    n_hours = len(result_df)

    coldstart_count = int(result_df["reactor_coldstart_triggered"].sum())

    lost_production_hours = int(result_df["reactor_state"].isin(["cold", "cold_start"]).sum())

    # Methane output: the Sabatier model only computes thermal state, the
    # actual mass flow is estimated here (see config.py section 9). Only
    # counted in the hours when the reactor is actually producing
    # (OPERATING state).
    h2_to_ch4_mass_ratio = config.CH4_MOLAR_MASS_G / (4 * config.H2_MOLAR_MASS_G)
    operating_mask = result_df["reactor_state"] == "operating"
    ch4_produced_kg = result_df.loc[operating_mask, "electrolyzer_h2_kg"].sum() * h2_to_ch4_mass_ratio
    methane_output_kwh = ch4_produced_kg * config.CH4_LHV_KWH_PER_KG

    # BESS deep discharge: the number of crossings below the 15%
    # (DEEP_DISCHARGE_THRESHOLD) mark (count/year), not the number of
    # hours spent below the threshold.
    below_threshold = result_df["bess_soc_fraction"] < config.DEEP_DISCHARGE_THRESHOLD
    dive_events = below_threshold & ~below_threshold.shift(1, fill_value=False)
    bess_deep_discharge = int(dive_events.sum())

    curtailed_kwh = float(result_df["bess_curtailed_kw"].sum())  # 1-hour steps -> kW sum = kWh sum

    reactor_warm_fraction = float((result_df["reactor_state"] == "operating").sum() / n_hours * 100)

    reserve_active_hours = int(result_df["reserve_active"].sum())

    return {
        "coldstart_count": coldstart_count,
        "lost_production_hours": lost_production_hours,
        "methane_output_kwh": methane_output_kwh,
        "bess_deep_discharge": bess_deep_discharge,
        "curtailed_kwh": curtailed_kwh,
        "reactor_warm_fraction_pct": reactor_warm_fraction,
        "reserve_active_hours": reserve_active_hours,
    }


# =============================================================================
# Standalone run: verification of step 7 per the documentation
#   "Runs the whole year, calculates the metrics.
#    Check: coldstart_count is reasonable (more than 10, but not 300)"
# =============================================================================
def main(location: str = "sevilla") -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    LOCATION = location

    print(f"Baseline (naive) simulation -- {config.LOCATIONS[LOCATION]['name']}\n")

    weather = pd.read_csv(config.LOCATIONS[LOCATION]["weather_csv"], index_col=0, parse_dates=True)
    result = simulate_baseline(weather, LOCATION)

    out_csv = config.RESULTS_DIR / f"baseline_{LOCATION}_hourly.csv"
    result.to_csv(out_csv)
    print(f"Hourly results saved: {out_csv}\n")

    metrics = compute_metrics(result)
    print("Annual metrics:")
    print(f"  coldstart_count:          {metrics['coldstart_count']:>10} count/yr")
    print(f"  lost_production_hours:    {metrics['lost_production_hours']:>10} hours/yr")
    print(f"  methane_output_kwh:       {metrics['methane_output_kwh']:>10,.0f} kWh/yr")
    print(f"  bess_deep_discharge:      {metrics['bess_deep_discharge']:>10} count/yr")
    print(f"  curtailed_kwh:            {metrics['curtailed_kwh']:>10,.0f} kWh/yr")
    print(f"  reactor_warm_fraction:    {metrics['reactor_warm_fraction_pct']:>10.1f} %")
    print(f"  reserve_active_hours:     {metrics['reserve_active_hours']:>10} hours/yr")

    coldstart_count = metrics["coldstart_count"]
    print()
    if 10 < coldstart_count < 300:
        print(f"CHECK OK: coldstart_count={coldstart_count} is within the expected (10, 300) range.")
    else:
        print(f"WARNING: coldstart_count={coldstart_count} is outside the expected (10, 300) range!")

    # --- Quick verification chart: reactor temperature + BESS state of charge for the whole year ---
    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True)

    axes[0].plot(result.index, result["reactor_temperature_c"], color="#dc2626", linewidth=0.6)
    axes[0].axhline(config.SABATIER_MIN_TEMP_C, color="#78716c", linestyle="--", linewidth=1, label="min_temp")
    axes[0].set_title(f"Reactor temperature -- baseline (naive) controller, {coldstart_count} cold starts")
    axes[0].set_ylabel("C")
    axes[0].legend(loc="lower right")
    axes[0].grid(alpha=0.3)

    axes[1].plot(result.index, result["bess_soc_fraction"] * 100, color="#2563eb", linewidth=0.6)
    axes[1].axhline(config.DEEP_DISCHARGE_THRESHOLD * 100, color="#78716c", linestyle="--", linewidth=1, label="deep discharge threshold")
    axes[1].set_title("BESS state of charge")
    axes[1].set_ylabel("%")
    axes[1].legend(loc="lower right")
    axes[1].grid(alpha=0.3)

    fig.tight_layout()
    out_png = config.RESULTS_DIR / f"baseline_{LOCATION}_verification.png"
    fig.savefig(out_png, dpi=120)
    print(f"\nChart saved: {out_png}")


if __name__ == "__main__":
    main()
