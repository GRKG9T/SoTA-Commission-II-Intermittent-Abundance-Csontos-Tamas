"""
models/dac_model.py -- DAC (direct air capture of CO2) delayed/ramped consumer model

The DAC unit captures CO2 from the air, which the Sabatier reactor
uses. Section 2.1's table in the documentation calls this a "delayed/
ramped consumer model" -- this "delayed/ramped" label is the key
difference from the electrolyzer: the DAC does not switch instantly to
full power/zero, but ramps up or down gradually over DAC_RAMP_HOURS.
This is more realistic (real DAC units also have a ramp-up/ramp-down
time), and in the simulation it also results in a softer change in
energy demand when the controller switches it on or off.
"""


class DACModel:
    """Simple, ramped power/CO2 model of the DAC unit."""

    def __init__(self, power_kw: float, ramp_hours: float, kwh_per_kg_co2: float):
        self.power_kw = power_kw
        self.ramp_hours = ramp_hours
        self.kwh_per_kg_co2 = kwh_per_kg_co2

        # Internal state: what fraction the DAC's power currently sits at
        # (0 = fully off, 1 = full nominal power). This is what makes it
        # a "delayed" consumer -- it cannot jump instantly from 0 to 1.
        self._power_fraction = 0.0

    def step(self, available_power_kw: float, command: str = "on") -> dict:
        """
        Executes one hourly step.

        available_power_kw: the power [kW] that can be allocated to the DAC.
        command:              "on" or "off" -- the controller's target state.

        Returns a dict:
            power_consumed_kw: power actually drawn [kW]
            co2_captured_kg:   CO2 captured this hour [kg]
            power_fraction:    the ramp state [0-1] -- how "spun up" it is
            is_running:        whether actual consumption is occurring this hour
        """
        target_fraction = 1.0 if command == "on" else 0.0
        step_size = 1.0 / self.ramp_hours

        if self._power_fraction < target_fraction:
            self._power_fraction = min(target_fraction, self._power_fraction + step_size)
        elif self._power_fraction > target_fraction:
            self._power_fraction = max(target_fraction, self._power_fraction - step_size)

        desired_power_kw = self._power_fraction * self.power_kw
        actual_power_kw = min(desired_power_kw, available_power_kw)

        # 1-hour step -> the kWh value is numerically equal to the kW value.
        co2_captured_kg = actual_power_kw / self.kwh_per_kg_co2

        return {
            "power_consumed_kw": actual_power_kw,
            "co2_captured_kg": co2_captured_kg,
            "power_fraction": self._power_fraction,
            "is_running": actual_power_kw > 0,
        }


# =============================================================================
# Standalone run: quick verification (step 5 -- simple, quickly testable model)
# =============================================================================
if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import config

    print("DAC model verification\n")

    dac = DACModel(
        power_kw=config.DAC_POWER_KW,
        ramp_hours=config.DAC_RAMP_HOURS,
        kwh_per_kg_co2=config.DAC_KWH_PER_KG_CO2,
    )
    print(f"power_kw={dac.power_kw} kW, ramp_hours={dac.ramp_hours} hours, {dac.kwh_per_kg_co2} kWh/kg CO2\n")

    n_ramp_steps = int(round(config.DAC_RAMP_HOURS / 1.0)) + 2  # watch the full ramp-up, and a bit beyond

    print("--- Ramp-up: 'on' command, plenty of energy available ---")
    for i in range(1, max(n_ramp_steps, 3) + 1):
        r = dac.step(available_power_kw=1e9, command="on")
        print(
            f"  hour {i}: fraction={r['power_fraction']:.2f}, "
            f"consumed={r['power_consumed_kw']:.1f} kW, CO2={r['co2_captured_kg']:.2f} kg, running={r['is_running']}"
        )
    assert r["power_fraction"] == 1.0, "Should be at full power at the end of the ramp-up!"

    print("\n--- Ramp-down: 'off' command ---")
    for i in range(1, max(n_ramp_steps, 3) + 1):
        r = dac.step(available_power_kw=1e9, command="off")
        print(
            f"  hour {i}: fraction={r['power_fraction']:.2f}, "
            f"consumed={r['power_consumed_kw']:.1f} kW, CO2={r['co2_captured_kg']:.2f} kg, running={r['is_running']}"
        )
    assert r["power_fraction"] == 0.0 and r["is_running"] is False, "Should be fully off at the end of the ramp-down!"

    print("\n--- Power limit test: 'on' command, but less power available than nominal ---")
    dac2 = DACModel(
        power_kw=config.DAC_POWER_KW,
        ramp_hours=config.DAC_RAMP_HOURS,
        kwh_per_kg_co2=config.DAC_KWH_PER_KG_CO2,
    )
    limited_power = config.DAC_POWER_KW / 2
    for i in range(1, max(n_ramp_steps, 3) + 1):
        r = dac2.step(available_power_kw=limited_power, command="on")
    print(
        f"  Available power: {limited_power:.0f} kW (half of nominal) -> "
        f"final power drawn: {r['power_consumed_kw']:.1f} kW"
    )
    assert abs(r["power_consumed_kw"] - limited_power) < 1e-6, "Should stay at the power limit, even though the ramp has fully finished!"

    print("\nOK: the ramp-up, ramp-down and power limit all worked as expected.")
