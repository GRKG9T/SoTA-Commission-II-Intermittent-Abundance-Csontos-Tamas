"""
control/strategies/base_strategy.py -- Common base class for every BESS control strategy

This is the project's new main question (replacing the earlier "is life
insurance better than naive control?" question): which life-insurance
strategy works, when, and why? To answer this, we build 7 different
strategies, each implementing the same common "interface" (the decide()
method), so that the simulation loop (simulation/strategy_sweep.py) can run
them uniformly, one after another -- only the controller changes, everything
else (PV/BESS/Sabatier/electrolyzer/DAC models, RTU layer) stays the same.

Note on BESS access: for every strategy, the electrolyzer+DAC may use only
PV surplus, never the BESS (exactly as in the project's earlier,
already-validated baseline_sim.py/smart_sim.py). We tried changing this once
(giving them BESS access up to a reserve threshold), but it turned out that
the maintenance energy need of just one winter night (~760 kWh) exceeds the
entire reserve range examined (max. 40% = 800 kWh) -- even a "perfect"
reserve would have lasted just barely one single night, with no chance
whatsoever of multi-day protection. See simulation/strategy_sweep.py for
the detailed explanation.

The difference between the 7 strategies is therefore not in the degree of
BESS access, but in when and based on what signal they fully switch off the
electrolyzer/DAC -- leaving more PV surplus for charging the BESS, before
the deficit occurs. The reactor's own maintenance can always draw on the
BESS's full range down to min_soc, regardless of whether the given strategy
is currently "active".
"""

from abc import ABC, abstractmethod

import numpy as np


class BaseStrategy(ABC):
    """
    Every concrete strategy (control/strategies/*.py) derives from this.

    The constructor deliberately accepts every possible parameter that any
    strategy might use -- so that the simulation loop can always create any
    strategy with the same call, and each individual strategy only uses the
    fields it needs (ignoring the rest).
    """

    #: Short, filename-friendly identifier (e.g. for result-CSV column values).
    name: str = "base"
    #: Human-readable name (for labeling charts).
    display_name: str = "Base strategy"
    #: On a 1-5 scale, set manually in each subclass -- see config.py's
    #: STRATEGY_COMPLEXITY dictionary.
    complexity: int = 1
    #: Whether this strategy needs a forecast (informational purposes only).
    needs_forecast: bool = False

    def __init__(
        self,
        *,
        bess_capacity_kwh: float,
        bess_min_soc: float,
        bess_max_soc: float,
        maintenance_kw: float,
        coldstart_kw: float,
        tau_hours: float,
        min_temp: float,
        electrolyzer_min_kw: float,
        pv_capacity_kw: float,
        forecast_pv_kw=None,
        threshold_hours: int = None,
        reserve_fraction: float = None,
        min_reserve_fraction: float = None,
        max_reserve_fraction: float = None,
        precharge_trigger_fraction: float = None,
    ):
        self.bess_capacity_kwh = bess_capacity_kwh
        self.bess_min_soc_kwh = bess_min_soc * bess_capacity_kwh
        self.bess_max_soc_kwh = bess_max_soc * bess_capacity_kwh
        self.maintenance_kw = maintenance_kw
        self.coldstart_kw = coldstart_kw
        self.tau_hours = tau_hours
        self.min_temp = min_temp
        self.electrolyzer_min_kw = electrolyzer_min_kw
        self.pv_capacity_kw = pv_capacity_kw

        # Only needed by strategies that use a forecast:
        self.forecast_pv_kw = forecast_pv_kw
        self.threshold_hours = threshold_hours
        self.reserve_fraction = reserve_fraction
        self.min_reserve_fraction = min_reserve_fraction
        self.max_reserve_fraction = max_reserve_fraction
        self.precharge_trigger_fraction = precharge_trigger_fraction

    @abstractmethod
    def decide(self, current_hour: int, system_state: dict) -> dict:
        """
        One hour's worth of decision-making. Every subclass must implement this.

        system_state keys (populated by simulation/strategy_sweep.py):
            pv_power_kw:               the current hour's actual PV production
            env_temp_c:                the current hour's ambient temperature
            reactor_state:              the reactor's current ReactorState
            reactor_temperature_c:      the reactor's current temperature [C]
            bess_soc_kwh:               the BESS's current state of charge [kWh]
            bess_discharge_available_kw: how much the BESS could output right
                                          now (per physical limits, without any reserve)
            total_available_kw:         pv_power_kw + bess_discharge_available_kw
                                          -- this is what the reactor's own
                                          decision uses, independent of the
                                          reserve

        Keys of the dict to be returned:
            life_insurance_active: bool -- for logging/metrics only
            reserve_kwh:            float -- how much to protect from the
                                     electrolyzer/DAC (see module docstring)
            electrolyzer_command:   "on" | "off"
            dac_command:             "on" | "off"
            reactor_command:         "operate" | "maintain" | "shutdown"
            reactor_reserved_kw:     float -- the power allotted to the
                                     reactor (see _decide_reactor())
        """
        raise NotImplementedError

    # -------------------------------------------------------------------
    # Common helper methods -- usable by every subclass
    # -------------------------------------------------------------------

    def _decide_reactor(self, pv_kw: float, reactor_state, total_available_kw: float):
        """
        The reactor's state-dependent decision -- every strategy uses this
        same logic (see the similar explanation in simulation/baseline_sim.py
        from step 7): the "is it worth producing" question is always decided
        from the actual PV (not from the forecast), avoiding a self-reinforcing
        loop in which the reactor would never cool down because it would
        never spend anything.

        The reactor uses total_available_kw (PV + BESS down to min_soc),
        regardless of how large a reserve the strategy has withheld from
        others. The reserve protects the reactor; it doesn't work against it.

        Returns: (reactor_command, reactor_reserved_kw)
        """
        can_produce = pv_kw >= self.electrolyzer_min_kw

        if reactor_state.value in ("operating", "maintenance"):
            if can_produce:
                return "operate", 0.0
            elif total_available_kw >= self.maintenance_kw:
                return "maintain", self.maintenance_kw
            else:
                return "shutdown", total_available_kw
        else:  # cold or cold_start
            if total_available_kw >= self.coldstart_kw:
                return "operate", self.coldstart_kw
            elif total_available_kw >= self.maintenance_kw:
                return "maintain", self.maintenance_kw
            else:
                return "shutdown", total_available_kw

    def _forecast_window(self, current_hour: int):
        """The next self.threshold_hours hours of forecast_pv_kw."""
        window_end = min(current_hour + self.threshold_hours, len(self.forecast_pv_kw))
        return self.forecast_pv_kw[current_hour:window_end]

    def _net_balance_deficit(self, forecast_window) -> float:
        """
        Expected production minus minimal need (the reactor's maintenance
        requirement), net sum over the window. Positive if the expected
        total production is not enough for maintenance (even if there's a
        surplus during the day -- only if it's not enough over the whole
        window). 0 if there is enough (or more) production.

        (For a detailed explanation of why this particular formula -- and
        not the sum of the individual deficit hours -- see the original
        documentation of control/controller.py from step 8.)
        """
        window = np.asarray(forecast_window, dtype=float)
        net_balance_kwh = float(window.sum() - self.maintenance_kw * len(window))
        return max(0.0, -net_balance_kwh)
