"""
models/pv_model.py -- PV plant power model

This module calculates how much electrical energy the solar plant
produces hour by hour. Its input is the PVGIS TMY weather dataset
(irradiance and temperature), its output is an hourly AC power time
series [kW].

The calculation uses the pvlib library's "PVWatts" physical model, which
goes through the following steps (all of this is done internally by
pvlib's ModelChain object -- we only need to supply the input
parameters):
    1. Sun position (azimuth, elevation) at the given hour and location
    2. Calculation of the total irradiance falling on the tilted panel
       plane (transposition)
    3. Estimation of the panel temperature (air temperature + irradiance + wind)
    4. DC power as a function of panel temperature (PVWatts DC model)
    5. AC power based on inverter efficiency (PVWatts AC model)

Important: pvlib works internally in SI units (Watts), so the values
given in kW in the constructor are converted to W, and converted back
to kW at the end -- the user doesn't need to see this, the PVModel
class communicates externally in kW.
"""

import pandas as pd
from pvlib.location import Location
from pvlib.modelchain import ModelChain
from pvlib.pvsystem import PVSystem
from pvlib.temperature import TEMPERATURE_MODEL_PARAMETERS


class PVModel:
    """A pvlib-based physical model of the PV plant."""

    def __init__(
        self,
        capacity_kw: float,
        tilt: float,
        azimuth: float,
        efficiency: float,
        latitude: float,
        longitude: float,
        altitude: float = 0,
        gamma_pdc: float = -0.004,
    ):
        self.capacity_kw = capacity_kw
        self.tilt = tilt
        self.azimuth = azimuth
        self.efficiency = efficiency
        self.latitude = latitude
        self.longitude = longitude
        self.altitude = altitude
        self.gamma_pdc = gamma_pdc

        self._last_result = None
        self._model_chain = self._build_model_chain()

    def _build_model_chain(self) -> ModelChain:
        pdc0_w = self.capacity_kw * 1000  # kW -> W, pvlib calculates in Watts

        # "open_rack_glass_glass": open-rack mounted, glass-glass panel --
        # a typical assumption for an outdoor, ground-mounted plant.
        temperature_params = TEMPERATURE_MODEL_PARAMETERS["sapm"]["open_rack_glass_glass"]

        system = PVSystem(
            surface_tilt=self.tilt,
            surface_azimuth=self.azimuth,
            module_parameters={
                "pdc0": pdc0_w,
                "gamma_pdc": self.gamma_pdc,
            },
            inverter_parameters={
                "pdc0": pdc0_w,
                "eta_inv_nom": self.efficiency,
            },
            temperature_model_parameters=temperature_params,
        )

        location = Location(
            latitude=self.latitude,
            longitude=self.longitude,
            altitude=self.altitude,
            tz="UTC",  # the PVGIS TMY data arrives with UTC timestamps
        )

        # aoi_model / spectral_model = "no_loss": we ignore the angle-of-
        # incidence and spectral losses -- the original purpose of the
        # PVWatts model is also simplification, and these second-order
        # effects don't matter for this project's goal (comparing control
        # strategies, not a precise panel-level energy yield estimate).
        return ModelChain(
            system,
            location,
            dc_model="pvwatts",
            ac_model="pvwatts",
            aoi_model="no_loss",
            spectral_model="no_loss",
        )

    @staticmethod
    def _prepare_weather(weather_df: pd.DataFrame) -> pd.DataFrame:
        """Renames the raw PVGIS columns to the names expected by pvlib."""
        required = ["G(h)", "Gb(n)", "Gd(h)", "T2m", "WS10m"]
        missing = [col for col in required if col not in weather_df.columns]
        if missing:
            raise ValueError(
                f"Missing columns in the weather data: {missing}. "
                f"Check whether you are using the CSV downloaded by "
                f"data_fetch/pvgis_fetch.py."
            )

        return pd.DataFrame(
            {
                "ghi": weather_df["G(h)"],      # global horizontal irradiance [W/m2]
                "dni": weather_df["Gb(n)"],      # direct normal irradiance [W/m2]
                "dhi": weather_df["Gd(h)"],      # diffuse horizontal irradiance [W/m2]
                "temp_air": weather_df["T2m"],   # air temperature [C]
                "wind_speed": weather_df["WS10m"],  # wind speed [m/s]
            },
            index=weather_df.index,
        )

    def simulate(self, weather_df: pd.DataFrame) -> pd.Series:
        """
        Runs the simulation over a weather dataset.

        weather_df: pandas DataFrame with a datetime index, and at least
                    the "G(h)", "Gb(n)", "Gd(h)", "T2m", "WS10m" columns
                    (this is exactly what pvgis_fetch.py's output looks like).

        Returns: pandas Series, hourly AC power [kW], with the same
                 timestamps as weather_df.
        """
        weather = self._prepare_weather(weather_df)
        self._model_chain.run_model(weather)

        ac_power_kw = self._model_chain.results.ac / 1000  # W -> kW
        ac_power_kw = ac_power_kw.clip(lower=0)  # clip negative (nighttime noise) values
        ac_power_kw.name = "pv_power_kw"

        self._last_result = ac_power_kw
        return ac_power_kw

    def annual_summary(self) -> dict:
        """
        Summary metrics for the most recent simulate() run.

        Returns: dict -- annual total production [kWh], peak power [kW],
                 capacity factor [%], specific yield [kWh/kWp/year].
        """
        if self._last_result is None:
            raise RuntimeError("Call simulate() with a weather dataset first!")

        power = self._last_result
        n_hours = len(power)

        annual_kwh = power.sum()  # sum of hourly kW values = kWh (1 hour * kW)
        peak_kw = power.max()
        capacity_factor_pct = annual_kwh / (self.capacity_kw * n_hours) * 100
        specific_yield = annual_kwh / self.capacity_kw

        return {
            "annual_kwh": annual_kwh,
            "peak_kw": peak_kw,
            "capacity_factor_pct": capacity_factor_pct,
            "specific_yield_kwh_per_kwp": specific_yield,
        }


# =============================================================================
# Standalone run: verification of step 2 per the documentation
#   - Plot the annual production curve (should look reasonable)
#   - Check: annual total between 1700-2200 kWh/kWp for Seville
# =============================================================================
if __name__ == "__main__":
    import sys
    from pathlib import Path

    import matplotlib

    matplotlib.use("Agg")  # save the figure to a file, no need for a screen-drawing window
    import matplotlib.pyplot as plt

    # Add the project root to the module search path so config.py can be
    # imported (this file is in the models/ subfolder).
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import config

    print("PV model verification -- using Seville data\n")

    sevilla = config.LOCATIONS["sevilla"]
    weather = pd.read_csv(sevilla["weather_csv"], index_col=0, parse_dates=True)

    pv = PVModel(
        capacity_kw=config.PV_CAPACITY_KW,
        tilt=config.PV_TILT,
        azimuth=config.PV_AZIMUTH,
        efficiency=config.PV_EFFICIENCY,
        latitude=sevilla["latitude"],
        longitude=sevilla["longitude"],
        altitude=sevilla["altitude_m"],
        gamma_pdc=config.PV_GAMMA_PDC,
    )

    power = pv.simulate(weather)
    summary = pv.annual_summary()

    print(f"Annual total production: {summary['annual_kwh']:>10,.0f} kWh")
    print(f"Peak power:               {summary['peak_kw']:>10,.1f} kW")
    print(f"Capacity factor:          {summary['capacity_factor_pct']:>10.1f} %")
    print(f"Specific yield:           {summary['specific_yield_kwh_per_kwp']:>10.0f} kWh/kWp/year")

    yield_kwh_per_kwp = summary["specific_yield_kwh_per_kwp"]
    print()
    if 1700 <= yield_kwh_per_kwp <= 2200:
        print(f"CHECK OK: {yield_kwh_per_kwp:.0f} kWh/kWp is within the expected 1700-2200 range.")
    else:
        print(f"WARNING: {yield_kwh_per_kwp:.0f} kWh/kWp falls OUTSIDE the expected 1700-2200 range!")

    # --- Chart: daily total production for the whole year + one sample week hour by hour ---
    daily_kwh = power.resample("D").sum()
    sample_week = power.iloc[24 * 180 : 24 * 187]  # around late June, a typical summer week

    fig, axes = plt.subplots(2, 1, figsize=(11, 7))

    axes[0].plot(daily_kwh.index, daily_kwh.values, color="#d97706")
    axes[0].set_title("Daily PV production -- Seville (TMY year)")
    axes[0].set_ylabel("kWh/day")
    axes[0].grid(alpha=0.3)

    axes[1].plot(sample_week.index, sample_week.values, color="#2563eb")
    axes[1].set_title("Sample week hourly power output (summer week)")
    axes[1].set_ylabel("kW")
    axes[1].grid(alpha=0.3)

    fig.tight_layout()
    out_path = config.RESULTS_DIR / "pv_model_verification.png"
    fig.savefig(out_path, dpi=120)
    print(f"\nFigure saved: {out_path}")
