"""
control/strategies/reactive_baseline.py -- Strategy 1: Reactive baseline

No forecast, no proactive decisions -- purely reactive behavior. The
electrolyzer+DAC are always "on" (never proactively switched off), and
since (see base_strategy.py) they can in any case only use PV surplus, this
exactly reproduces the project's earlier, already-validated baseline
(simulation/baseline_sim.py), just now through the common strategy
interface. This is the reference point against which the other 6
strategies are compared.
"""

from control.strategies.base_strategy import BaseStrategy


class ReactiveBaselineStrategy(BaseStrategy):
    name = "reactive_baseline"
    display_name = "1. Reactive Baseline"
    complexity = 1
    needs_forecast = False

    def decide(self, current_hour: int, system_state: dict) -> dict:
        pv_kw = system_state["pv_power_kw"]
        reactor_command, reactor_reserved_kw = self._decide_reactor(
            pv_kw, system_state["reactor_state"], system_state["total_available_kw"]
        )

        return {
            "life_insurance_active": False,
            "reserve_kwh": 0.0,
            "electrolyzer_command": "on",
            "dac_command": "on",
            "reactor_command": reactor_command,
            "reactor_reserved_kw": reactor_reserved_kw,
        }
