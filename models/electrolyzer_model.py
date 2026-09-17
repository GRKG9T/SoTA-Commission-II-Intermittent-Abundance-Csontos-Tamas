"""
models/electrolyzer_model.py -- Simplified electrolyzer consumer model

The electrolyzer uses electrical energy to split water (H2O -> H2 + O2).
This model is a "parametric consumer model" (as section 2.1's table in
the documentation calls it): it has no state/inertia of its own -- every
hour it simply draws as much power as the available energy and its own
load limits (min/max) allow, and produces hydrogen proportionally.

If the available power falls below the minimum load (ELECTROLYZER_MIN_KW),
the electrolyzer cannot operate (turndown limit) -- in that case it shuts
down completely, it does not run at partial load below that.
"""


class ElectrolyzerModel:
    """Simple, stateless power/H2 model of the electrolyzer."""

    def __init__(self, min_kw: float, max_kw: float, kwh_per_kg_h2: float):
        self.min_kw = min_kw
        self.max_kw = max_kw
        self.kwh_per_kg_h2 = kwh_per_kg_h2

    def step(self, available_power_kw: float, command: str = "on") -> dict:
        """
        Executes one hourly step.

        available_power_kw: the power [kW] that can be allocated to the
                             electrolyzer (already decided by the
                             controller/RTU).
        command:              "on" or "off" -- whether the controller
                               switched it on or off this hour.

        Returns a dict:
            power_consumed_kw: power actually drawn [kW]
            h2_produced_kg:    hydrogen produced this hour [kg]
            is_running:        whether it is operating this hour
        """
        if command == "off":
            power_consumed_kw = 0.0
        else:
            power_consumed_kw = min(available_power_kw, self.max_kw)
            if power_consumed_kw < self.min_kw:
                power_consumed_kw = 0.0  # does not start below the turndown minimum

        # 1-hour step -> the kWh value is numerically equal to the kW value.
        h2_produced_kg = power_consumed_kw / self.kwh_per_kg_h2

        return {
            "power_consumed_kw": power_consumed_kw,
            "h2_produced_kg": h2_produced_kg,
            "is_running": power_consumed_kw > 0,
        }


# =============================================================================
# Standalone run: quick verification (step 5 -- simple, quickly testable model)
# =============================================================================
if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import config

    print("Electrolyzer model verification\n")

    ely = ElectrolyzerModel(
        min_kw=config.ELECTROLYZER_MIN_KW,
        max_kw=config.ELECTROLYZER_MAX_KW,
        kwh_per_kg_h2=config.ELECTROLYZER_KWH_PER_KG_H2,
    )
    print(f"min_kw={ely.min_kw} kW, max_kw={ely.max_kw} kW, {ely.kwh_per_kg_h2} kWh/kg H2\n")

    scenarios = [
        (20, "on", "below turndown -- should not operate"),
        (300, "on", "within range -- uses it all"),
        (900, "on", "above max_kw -- should be capped at max_kw"),
        (300, "off", "controller switched it off -- should not operate"),
    ]

    for available_kw, command, description in scenarios:
        r = ely.step(available_power_kw=available_kw, command=command)
        print(
            f"  available={available_kw:>4} kW, command={command:>3} ({description})\n"
            f"    -> consumed={r['power_consumed_kw']:>5.1f} kW, "
            f"H2={r['h2_produced_kg']:.2f} kg, running={r['is_running']}"
        )

    r_low = ely.step(available_power_kw=20, command="on")
    r_mid = ely.step(available_power_kw=300, command="on")
    r_high = ely.step(available_power_kw=900, command="on")
    r_off = ely.step(available_power_kw=300, command="off")

    assert r_low["is_running"] is False, "Should not operate below turndown!"
    assert abs(r_mid["power_consumed_kw"] - 300) < 1e-6, "Power within range should be used in full!"
    assert abs(r_high["power_consumed_kw"] - ely.max_kw) < 1e-6, "Should be capped at max_kw!"
    assert r_off["is_running"] is False, "Should not operate when switched off!"
    print("\nOK: all scenarios behaved as expected.")
