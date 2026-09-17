"""
models/bess_model.py -- BESS (battery energy storage system) energy balance model

A simple model that tracks the BESS's state of charge (SOC, measured in
kWh) in hourly steps. Real-world BESS complexity (degradation,
temperature effects, cell-level balancing) is deliberately not
modelled -- these are negligible for the project's focus (comparing
control strategies).

Sign convention in the step() method:
    power_kw > 0  -> charging (e.g. feeding PV surplus into the BESS)
    power_kw < 0  -> discharging (covering consumption from the BESS)

Efficiency causes losses in both directions: when charging, only part
of the incoming energy is actually stored (the rest is lost as heat);
when discharging, only part of the stored energy actually reaches the
consumers as usable power.
"""


class BESSModel:
    """BESS energy balance model -- calculates in hourly steps."""

    def __init__(
        self,
        capacity_kwh: float,
        max_charge_kw: float,
        max_discharge_kw: float,
        min_soc: float,
        max_soc: float,
        efficiency: float,
        initial_soc: float = None,
    ):
        self.capacity_kwh = capacity_kwh
        self.max_charge_kw = max_charge_kw
        self.max_discharge_kw = max_discharge_kw
        self.min_soc = min_soc
        self.max_soc = max_soc
        self.efficiency = efficiency

        # If no initial state of charge is given separately, the BESS
        # starts "full" (at max_soc level) -- a reasonable default for
        # the start of a new simulation (e.g. after a one-day period).
        initial_fraction = self.max_soc if initial_soc is None else initial_soc
        self.soc_kwh = initial_fraction * self.capacity_kwh

    @property
    def min_soc_kwh(self) -> float:
        return self.min_soc * self.capacity_kwh

    @property
    def max_soc_kwh(self) -> float:
        return self.max_soc * self.capacity_kwh

    @property
    def soc_fraction(self) -> float:
        """The current state of charge, expressed as a [0-1] fraction."""
        return self.soc_kwh / self.capacity_kwh

    def get_available_kwh(self, reserve_kwh: float = 0) -> float:
        """
        The energy actually available for discharge [kWh]: the current
        state of charge minus the physical minimum (min_soc) and the
        reserve held back by the RTU.
        """
        effective_floor_kwh = self.min_soc_kwh + reserve_kwh
        return max(0.0, self.soc_kwh - effective_floor_kwh)

    def step(self, power_kw: float, reserve_kwh: float = 0) -> dict:
        """
        Executes one hourly step.

        power_kw:    the requested power. Positive = charging (offering
                     PV surplus to the BESS), negative = discharging
                     (requesting the BESS to cover consumption).
        reserve_kwh: the capacity [kWh] held back by the RTU. This is the
                     amount of energy protected above the physical min_soc
                     minimum -- the BESS cannot be discharged below this
                     level. It does not limit charging, only discharging.

        Returns a dict:
            actual_power_kw: the power actually transferred, using the
                              same sign convention as power_kw
            soc_kwh:          the new state of charge after this step
            curtailed_kw:     what could not be accommodated -- when
                               charging, the PV surplus that could not be
                               stored (curtailed); when discharging, the
                               demand that could not be met (unserved)
        """
        if power_kw > 0:
            return self._charge(power_kw)
        elif power_kw < 0:
            return self._discharge(-power_kw, reserve_kwh)
        else:
            return {
                "actual_power_kw": 0.0,
                "soc_kwh": self.soc_kwh,
                "curtailed_kw": 0.0,
            }

    def _charge(self, power_kw: float) -> dict:
        power_capped_kw = min(power_kw, self.max_charge_kw)

        # This is how much input power the remaining headroom up to
        # max_soc could actually absorb, accounting for the charging loss
        # (1-hour step -> numerically kWh = kW).
        headroom_kwh = self.max_soc_kwh - self.soc_kwh
        max_power_for_headroom_kw = headroom_kwh / self.efficiency

        actual_power_kw = max(0.0, min(power_capped_kw, max_power_for_headroom_kw))
        curtailed_kw = power_kw - actual_power_kw

        self.soc_kwh += actual_power_kw * self.efficiency
        self.soc_kwh = min(self.soc_kwh, self.max_soc_kwh)  # guard against rounding errors

        return {
            "actual_power_kw": actual_power_kw,
            "soc_kwh": self.soc_kwh,
            "curtailed_kw": curtailed_kw,
        }

    def _discharge(self, requested_kw: float, reserve_kwh: float) -> dict:
        power_capped_kw = min(requested_kw, self.max_discharge_kw)

        # This is how much output power the available energy (after
        # subtracting the reserve and the minimum) can actually deliver,
        # accounting for the discharge loss.
        available_kwh = self.get_available_kwh(reserve_kwh)
        max_power_from_available_kw = available_kwh * self.efficiency

        actual_delivered_kw = max(0.0, min(power_capped_kw, max_power_from_available_kw))
        curtailed_kw = requested_kw - actual_delivered_kw

        self.soc_kwh -= actual_delivered_kw / self.efficiency
        self.soc_kwh = max(self.soc_kwh, 0.0)  # guard against rounding errors

        return {
            "actual_power_kw": -actual_delivered_kw,
            "soc_kwh": self.soc_kwh,
            "curtailed_kw": curtailed_kw,
        }


# =============================================================================
# Standalone run: verification of step 3 per the documentation
#   "Simple test: charge and discharge over a few steps, state of charge should be reasonable"
# =============================================================================
if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import config

    print("BESS model verification\n")

    bess = BESSModel(
        capacity_kwh=config.BESS_CAPACITY_KWH,
        max_charge_kw=config.BESS_MAX_CHARGE_KW,
        max_discharge_kw=config.BESS_MAX_DISCHARGE_KW,
        min_soc=config.BESS_MIN_SOC,
        max_soc=config.BESS_MAX_SOC,
        efficiency=config.BESS_EFFICIENCY,
        initial_soc=0.30,  # start deliberately low, so there is room to charge
    )

    print(
        f"Capacity: {bess.capacity_kwh:.0f} kWh | "
        f"min SOC: {bess.min_soc_kwh:.0f} kWh | max SOC: {bess.max_soc_kwh:.0f} kWh"
    )
    print(f"Initial state of charge: {bess.soc_kwh:.0f} kWh ({bess.soc_fraction:.0%})\n")

    print("--- Test 1: power limit -- requesting 1500 kW charge (max_charge_kw = "
          f"{bess.max_charge_kw:.0f} kW) ---")
    r = bess.step(power_kw=1500)
    print(
        f"  requested=1500 kW -> actual={r['actual_power_kw']:.1f} kW, "
        f"curtailed={r['curtailed_kw']:.1f} kW, SOC={r['soc_kwh']:.0f} kWh ({bess.soc_fraction:.1%})"
    )
    assert abs(r["actual_power_kw"] - bess.max_charge_kw) < 1e-6, "The power limit should have been enforced!"
    print("  OK: the power limit (max_charge_kw) was enforced.\n")

    print("--- Test 2: charging at 400 kW for 3 hours -- should show the BESS filling up ---")
    for hour in range(1, 4):
        r = bess.step(power_kw=400)
        print(
            f"  hour {hour}: requested=400 kW -> actual={r['actual_power_kw']:.1f} kW, "
            f"SOC={r['soc_kwh']:.0f} kWh ({bess.soc_fraction:.1%}), curtailed={r['curtailed_kw']:.1f} kW"
        )
    print(f"  OK: as SOC approaches max_soc ({bess.max_soc_kwh:.0f} kWh), more and more energy is curtailed.\n")

    print("--- Test 3: discharging at 300 kW for 5 hours -- SOC should decrease gradually ---")
    for hour in range(1, 6):
        r = bess.step(power_kw=-300)
        print(
            f"  hour {hour}: requested=-300 kW -> actual={r['actual_power_kw']:.1f} kW, "
            f"SOC={r['soc_kwh']:.0f} kWh ({bess.soc_fraction:.1%}), unserved={r['curtailed_kw']:.1f} kW"
        )
    print("  OK: discharging correctly reduced the state of charge.\n")

    print("--- Test 4: reactor reserve -- reserve the entire free energy, "
          "discharge should be blocked ---")
    available = bess.get_available_kwh(reserve_kwh=0)
    reserve_kwh = available  # reserve the entire currently-available energy
    print(f"  Freely available energy without reserve: {available:.0f} kWh")
    print(f"  Reserve set to: {reserve_kwh:.0f} kWh")
    r = bess.step(power_kw=-100, reserve_kwh=reserve_kwh)
    print(
        f"  requested=-100 kW -> actual={r['actual_power_kw']:.1f} kW, "
        f"unserved={r['curtailed_kw']:.1f} kW (expected to be about 100, since the reserve blocks it)"
    )
    assert abs(r["actual_power_kw"]) < 1e-6, "The reserve should have fully blocked the discharge!"
    print("  OK: the reserve did indeed block the discharge.\n")

    print("--- Final check: did SOC stay within the [min_soc, max_soc] range throughout? ---")
    if bess.min_soc_kwh - 1e-6 <= bess.soc_kwh <= bess.max_soc_kwh + 1e-6:
        print(f"  OK: SOC={bess.soc_kwh:.1f} kWh is within the [{bess.min_soc_kwh:.0f}, {bess.max_soc_kwh:.0f}] kWh range.")
    else:
        print(f"  ERROR: SOC={bess.soc_kwh:.1f} kWh falls OUTSIDE the expected range!")
