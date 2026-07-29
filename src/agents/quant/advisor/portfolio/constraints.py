"""Contraintes de portefeuille versionnées (Lot 8) : caps d'exposition +
granularité de mise (tranche minimale ADR-ADV-002). Config pure, chargée depuis
`configs/advisor/portfolio_policy.json`."""

from __future__ import annotations

import json
import pathlib
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from ..domain.money import ZERO

_CONFIG_PATH = (
    pathlib.Path(__file__).resolve().parents[5]
    / "configs" / "advisor" / "portfolio_policy.json"
)


@dataclass(frozen=True)
class PortfolioCaps:
    max_event_exposure_fraction: Decimal
    max_participant_exposure_fraction: Decimal
    max_competition_exposure_fraction: Decimal
    max_bookmaker_exposure_fraction: Decimal
    stake_granularity: Decimal
    min_line_stake: Decimal

    def __post_init__(self) -> None:
        if self.stake_granularity <= ZERO:
            raise ValueError("stake_granularity doit être > 0")
        if self.min_line_stake < ZERO:
            raise ValueError("min_line_stake doit être >= 0")

    def round_down(self, amount: Decimal) -> Decimal:
        """Arrondi vers le BAS au pas de granularité (ne dépasse jamais un cap)."""
        if amount <= ZERO:
            return ZERO
        return (amount // self.stake_granularity) * self.stake_granularity


def load_portfolio_caps(path: pathlib.Path = _CONFIG_PATH) -> Mapping[str, PortfolioCaps]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        name: PortfolioCaps(
            max_event_exposure_fraction=Decimal(p["max_event_exposure_fraction"]),
            max_participant_exposure_fraction=Decimal(p["max_participant_exposure_fraction"]),
            max_competition_exposure_fraction=Decimal(p["max_competition_exposure_fraction"]),
            max_bookmaker_exposure_fraction=Decimal(p["max_bookmaker_exposure_fraction"]),
            stake_granularity=Decimal(p["stake_granularity"]),
            min_line_stake=Decimal(p["min_line_stake"]),
        )
        for name, p in data["profiles"].items()
    }
