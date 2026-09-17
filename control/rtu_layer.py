"""
control/rtu_layer.py -- Simulated RTU (Remote Terminal Unit) layer

Simulates the deterministic protection of a real industrial RTU. Every
control decision, including the proposal from the optimizing (life
insurance) layer, passes through this layer before being executed. The RTU
is not "smart": it doesn't optimize, it only checks simple, hard rules, and
corrects or rejects anything that would violate them.

This is the "safety net" in the project's architecture: whatever the
control layer (control/controller.py -- built in step 8) proposes, the RTU
never lets it through if it would be physically or safety-wise invalid.

An important separation of responsibilities: the RTU does not decide which
subsystem needs to be shut down in the event of an energy shortfall (that
is the control layer's job, see section 4.6) -- the RTU only ensures that
whatever it receives stays within the physical limits (BESS capacity,
loading maximums, reserve protection).
"""


class RTULayer:
    """Deterministic enforcement of the hard physical/safety limits."""

    def __init__(
        self,
        bess_capacity_kwh: float,
        bess_min_soc: float,
        bess_max_soc: float,
        bess_max_charge_kw: float,
        bess_max_discharge_kw: float,
        electrolyzer_max_kw: float,
        dac_max_kw: float,
    ):
        self.bess_capacity_kwh = bess_capacity_kwh
        self.bess_min_soc = bess_min_soc
        self.bess_max_soc = bess_max_soc
        self.bess_max_charge_kw = bess_max_charge_kw
        self.bess_max_discharge_kw = bess_max_discharge_kw
        self.electrolyzer_max_kw = electrolyzer_max_kw
        self.dac_max_kw = dac_max_kw

    @property
    def bess_min_soc_kwh(self) -> float:
        return self.bess_min_soc * self.bess_capacity_kwh

    @property
    def bess_max_soc_kwh(self) -> float:
        return self.bess_max_soc * self.bess_capacity_kwh

    def arbitrate(self, command_dict: dict, system_state: dict) -> dict:
        """
        Approving/correcting the control layer's proposal.

        command_dict keys (all optional, a missing key = 0 or a neutral
        default):
            bess_power_kw:          requested BESS power
                                     (positive = charging, negative = discharging)
            reserve_kwh:            reactor reserve requested by the controller [kWh]
            electrolyzer_power_kw:  requested electrolyzer power [kW]
            dac_power_kw:           requested DAC power [kW]
            reactor_command:        "operate" | "maintain" | "shutdown"

        system_state keys:
            bess_soc_kwh: the BESS's current state of charge [kWh]

        Returns the approved (possibly corrected) commands, with the same
        key structure.
        """
        bess_soc_kwh = system_state["bess_soc_kwh"]

        approved_bess_power_kw = self._arbitrate_bess_power(
            requested_kw=command_dict.get("bess_power_kw", 0.0),
            reserve_kwh=max(0.0, command_dict.get("reserve_kwh", 0.0)),
            bess_soc_kwh=bess_soc_kwh,
        )

        return {
            "bess_power_kw": approved_bess_power_kw,
            "reserve_kwh": max(0.0, command_dict.get("reserve_kwh", 0.0)),
            "electrolyzer_power_kw": self._clip(
                command_dict.get("electrolyzer_power_kw", 0.0), 0.0, self.electrolyzer_max_kw
            ),
            "dac_power_kw": self._clip(command_dict.get("dac_power_kw", 0.0), 0.0, self.dac_max_kw),
            "reactor_command": command_dict.get("reactor_command", "maintain"),
        }

    def _arbitrate_bess_power(self, requested_kw: float, reserve_kwh: float, bess_soc_kwh: float) -> float:
        # 1. Power limit: max charge/discharge rate.
        power_kw = self._clip(requested_kw, -self.bess_max_discharge_kw, self.bess_max_charge_kw)

        if power_kw > 0:
            # 2a. When charging: it may not exceed max_soc.
            headroom_kwh = max(0.0, self.bess_max_soc_kwh - bess_soc_kwh)
            power_kw = min(power_kw, headroom_kwh)

        elif power_kw < 0:
            # 2b. When discharging: it may not go below min_soc, and it may
            # not touch the reactor reserve (reserve lockout) -- the two
            # protections together determine the energy actually usable.
            protected_floor_kwh = self.bess_min_soc_kwh + reserve_kwh
            available_kwh = max(0.0, bess_soc_kwh - protected_floor_kwh)
            power_kw = -min(abs(power_kw), available_kwh)

        return power_kw

    @staticmethod
    def _clip(value: float, low: float, high: float) -> float:
        return max(low, min(value, high))

    def fallback_mode(self, system_state: dict) -> dict:
        """
        If the weather forecast is unavailable, the RTU issues this
        maximally conservative, safe command set on its own (bypassing the
        control layer): all consumers shut down, the reactor goes into
        maintenance mode (so it doesn't cool down), and the BESS's entire
        freely usable energy is held back for reactor maintenance -- this
        is the safest state we can reach without any information.
        """
        bess_soc_kwh = system_state["bess_soc_kwh"]
        reserve_kwh = max(0.0, bess_soc_kwh - self.bess_min_soc_kwh)

        return {
            "bess_power_kw": 0.0,
            "reserve_kwh": reserve_kwh,
            "electrolyzer_power_kw": 0.0,
            "dac_power_kw": 0.0,
            "reactor_command": "maintain",
        }


# =============================================================================
# Standalone run: verification of step 6 per the documentation
#   "Test: try to violate the limits, the RTU prevents it"
# =============================================================================
if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import config

    print("RTU layer verification\n")

    rtu = RTULayer(
        bess_capacity_kwh=config.BESS_CAPACITY_KWH,
        bess_min_soc=config.BESS_MIN_SOC,
        bess_max_soc=config.BESS_MAX_SOC,
        bess_max_charge_kw=config.BESS_MAX_CHARGE_KW,
        bess_max_discharge_kw=config.BESS_MAX_DISCHARGE_KW,
        electrolyzer_max_kw=config.ELECTROLYZER_MAX_KW,
        dac_max_kw=config.DAC_POWER_KW,
    )
    print(
        f"BESS: {rtu.bess_min_soc_kwh:.0f}-{rtu.bess_max_soc_kwh:.0f} kWh, "
        f"max charge/discharge: {rtu.bess_max_charge_kw:.0f}/{rtu.bess_max_discharge_kw:.0f} kW\n"
    )

    print("--- Test 1: excessive charge power (2x max_charge_kw) ---")
    state = {"bess_soc_kwh": rtu.bess_capacity_kwh * 0.2}  # low SOC, so that headroom isn't the limiting factor
    cmd = {"bess_power_kw": rtu.bess_max_charge_kw * 2}
    approved = rtu.arbitrate(cmd, state)
    print(f"  requested={cmd['bess_power_kw']:.0f} kW -> approved={approved['bess_power_kw']:.0f} kW")
    assert approved["bess_power_kw"] == rtu.bess_max_charge_kw, "The power limit should have been enforced!"
    print("  OK: the power limit was enforced.\n")

    print("--- Test 2: charging with an almost-full BESS (SOC limit test) ---")
    near_full_soc = rtu.bess_max_soc_kwh - 20  # only 20 kWh of headroom left
    state = {"bess_soc_kwh": near_full_soc}
    cmd = {"bess_power_kw": 500}  # requesting far more than the available headroom
    approved = rtu.arbitrate(cmd, state)
    print(f"  headroom=20 kWh, requested=500 kW -> approved={approved['bess_power_kw']:.1f} kW")
    assert abs(approved["bess_power_kw"] - 20) < 1e-6, "The max_soc limit should have been enforced!"
    print("  OK: the SOC limit (max_soc) was enforced.\n")

    print("--- Test 3: excessive discharge power (2x max_discharge_kw) ---")
    state = {"bess_soc_kwh": rtu.bess_capacity_kwh * 0.8}  # high SOC, so that available energy isn't the limiting factor
    cmd = {"bess_power_kw": -rtu.bess_max_discharge_kw * 2}
    approved = rtu.arbitrate(cmd, state)
    print(f"  requested={cmd['bess_power_kw']:.0f} kW -> approved={approved['bess_power_kw']:.0f} kW")
    assert approved["bess_power_kw"] == -rtu.bess_max_discharge_kw, "The power limit should have been enforced!"
    print("  OK: the power limit was enforced.\n")

    print("--- Test 4: discharging with an almost-empty BESS (min_soc limit test) ---")
    near_empty_soc = rtu.bess_min_soc_kwh + 15  # only 15 kWh is dischargeable
    state = {"bess_soc_kwh": near_empty_soc}
    cmd = {"bess_power_kw": -500}
    approved = rtu.arbitrate(cmd, state)
    print(f"  dischargeable=15 kWh, requested=-500 kW -> approved={approved['bess_power_kw']:.1f} kW")
    assert abs(approved["bess_power_kw"] + 15) < 1e-6, "The min_soc limit should have been enforced!"
    print("  OK: the SOC limit (min_soc) was enforced.\n")

    print("--- Test 5: reactor reserve lockout -- discharge may not touch the reserved portion ---")
    soc = rtu.bess_min_soc_kwh + 100  # 100 kWh would be freely usable without a reserve
    state = {"bess_soc_kwh": soc}
    cmd = {"bess_power_kw": -80, "reserve_kwh": 70}  # 70 kWh reserved -> only 30 kWh remains free
    approved = rtu.arbitrate(cmd, state)
    print(
        f"  free=100 kWh, reserve=70 kWh (30 remaining), requested=-80 kW -> approved={approved['bess_power_kw']:.1f} kW"
    )
    assert abs(approved["bess_power_kw"] + 30) < 1e-6, "The reserve lockout should have been enforced!"
    print("  OK: the reserve lockout was enforced -- the reserved energy remained untouched.\n")

    print("--- Test 6: excessive electrolyzer/DAC power request ---")
    cmd = {
        "electrolyzer_power_kw": rtu.electrolyzer_max_kw * 3,
        "dac_power_kw": rtu.dac_max_kw * 3,
    }
    approved = rtu.arbitrate(cmd, {"bess_soc_kwh": rtu.bess_capacity_kwh * 0.5})
    print(
        f"  electrolyzer: requested={cmd['electrolyzer_power_kw']:.0f} kW -> approved={approved['electrolyzer_power_kw']:.0f} kW"
    )
    print(f"  DAC: requested={cmd['dac_power_kw']:.0f} kW -> approved={approved['dac_power_kw']:.0f} kW")
    assert approved["electrolyzer_power_kw"] == rtu.electrolyzer_max_kw
    assert approved["dac_power_kw"] == rtu.dac_max_kw
    print("  OK: both loading limits were enforced.\n")

    print("--- Test 7: fallback mode (forecast unavailable) ---")
    state = {"bess_soc_kwh": rtu.bess_capacity_kwh * 0.6}
    safe_cmd = rtu.fallback_mode(state)
    print(f"  fallback commands: {safe_cmd}")
    assert safe_cmd["reactor_command"] == "maintain"
    assert safe_cmd["electrolyzer_power_kw"] == 0.0 and safe_cmd["dac_power_kw"] == 0.0
    assert safe_cmd["reserve_kwh"] > 0
    print("  OK: fallback mode shuts everything down, and puts the reactor into maintenance mode.")
