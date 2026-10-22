"""Materialize an auditable Phase 8 copy of D's planner with ablation hooks.

The frozen Phase 5 source is intentionally not edited. This script copies the
current RescuePriorityOptimizer._optimize implementation and applies narrowly
checked substitutions for experimental knobs. The resulting module records
the exact source SHA-256 and has a parity test against the frozen D policy.
"""

from __future__ import annotations

import hashlib
from inspect import getsource
from pathlib import Path

from lowalt6g.optimizer import RescuePriorityOptimizer


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src/lowalt6g/optimizer.py"
TARGET = ROOT / "src/lowalt6g/phase8_d_optimizer.py"


def substitute(source: str, old: str, new: str, expected: int = 1) -> str:
    count = source.count(old)
    if count != expected:
        raise RuntimeError(f"expected {expected} occurrence(s) of {old!r}, found {count}")
    return source.replace(old, new)


def main() -> None:
    method = getsource(RescuePriorityOptimizer._optimize)
    method = substitute(method, "sorted(geometrically_feasible)[:64]", "sorted(geometrically_feasible)[: self.candidate_limit]")
    method = substitute(method, "candidate_ranks: dict[tuple[int, int], tuple[float, ...]] = {}", "candidate_ranks: dict[tuple[int, int], tuple[float, ...]] = {}\n        candidate_energies: dict[tuple[int, int], float] = {}")
    method = substitute(method, "-float(switches),", "-float(switches) * self.switch_penalty_weight,")
    method = substitute(method, "if not rescue_tier_improves:", "if self.suppress_switch_without_rescue_gain and not rescue_tier_improves:")
    method = substitute(method, "candidate_ranks[(round(target.x_km / 0.005), round(target.y_km / 0.005))] = rank", "candidate_key = (round(target.x_km / 0.005), round(target.y_km / 0.005))\n            candidate_ranks[candidate_key] = rank\n            candidate_energies[candidate_key] = full_sortie_energy")
    method = substitute(method, "self.last_planned_sortie_energy_wh = -best_rank[8]", "best_key = (round(best_position.x_km / 0.005), round(best_position.y_km / 0.005))\n        self.last_planned_sortie_energy_wh = candidate_energies[best_key]")
    method = substitute(method, "-full_sortie_energy,", "-full_sortie_energy if self.energy_tiebreak_enabled else 0.0,")
    method = substitute(method, "float(rescue_user_ticks),\n                float(predicted_recovery_ticks is not None),", "float(rescue_user_ticks if self.rescue_priority_enabled else rescue_user_ticks + ordinary_user_ticks),\n                float(predicted_recovery_ticks is not None) if self.rescue_priority_enabled else float(ordinary_user_ticks),")
    method = substitute(method, "rescue_tier_improves = (\n                    best_rank[0] > held_rank[0]\n                    or best_rank[1] > held_rank[1]\n                    or best_rank[3] > held_rank[3]\n                    or best_rank[4] > held_rank[4]\n                )", "rescue_tier_improves = (\n                    (\n                        best_rank[0] > held_rank[0]\n                        or best_rank[1] > held_rank[1]\n                        or best_rank[3] > held_rank[3]\n                        or best_rank[4] > held_rank[4]\n                    )\n                    if self.rescue_priority_enabled\n                    else best_rank[0] > held_rank[0]\n                )")

    source_hash = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    module = f'''"""Phase 8 experimental D optimizer copied from the frozen Phase 5 implementation.

Source file SHA-256: {source_hash}
Only candidate cap, switch suppression/tie-break, energy tie-break, and rescue
lexicographic priority are exposed as experiment switches. Feasibility, full
sortie energy, return-to-station reserve, radio/backhaul constraints and the
runtime actuator are inherited unchanged.
"""

from __future__ import annotations

import math
from .energy_budget import sortie_energy_wh
from .engine import distance_km, evaluate_network
from .models import Network, Position
from .optimizer import ControlDecision, NetworkDiagnosis, RescuePriorityOptimizer, current_snapshot_by_id
from .models import NetworkSnapshot
from .policies import GreedyRelayPolicy

SOURCE_OPTIMIZER_SHA256 = "{source_hash}"


class Phase8RescuePriorityOptimizer(RescuePriorityOptimizer):
    def __init__(
        self,
        config,
        *,
        candidate_limit: int = 64,
        suppress_switch_without_rescue_gain: bool = True,
        energy_tiebreak_enabled: bool = True,
        rescue_priority_enabled: bool = True,
        switch_penalty_weight: float = 1.0,
    ) -> None:
        super().__init__(config)
        if candidate_limit < 1 or switch_penalty_weight < 0:
            raise ValueError("candidate_limit must be positive and switch penalty non-negative")
        self.candidate_limit = candidate_limit
        self.suppress_switch_without_rescue_gain = suppress_switch_without_rescue_gain
        self.energy_tiebreak_enabled = energy_tiebreak_enabled
        self.rescue_priority_enabled = rescue_priority_enabled
        self.switch_penalty_weight = switch_penalty_weight

{method}
'''
    TARGET.write_text(module, encoding="utf-8", newline="\n")
    print(f"Wrote {TARGET.relative_to(ROOT)} using optimizer SHA-256 {source_hash}")


if __name__ == "__main__":
    main()
