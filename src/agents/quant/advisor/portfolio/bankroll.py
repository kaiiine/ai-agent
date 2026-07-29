"""Suivi du budget global d'un portefeuille (PRD §13). Le budget d'une allocation
est `min(bankroll, max_total_stake)` ; il décroît à chaque ligne. La bankroll
n'est jamais saturée de force : le reliquat est `unallocated_bankroll`."""

from __future__ import annotations

from decimal import Decimal

from ..domain.money import ZERO


class Budget:
    def __init__(self, total: Decimal):
        self._remaining = total

    def remaining(self) -> Decimal:
        return self._remaining

    def allocate(self, stake: Decimal) -> None:
        self._remaining -= stake
        if self._remaining < ZERO:                 # garde-fou : jamais de sur-allocation
            raise ValueError("sur-allocation du budget de portefeuille")
