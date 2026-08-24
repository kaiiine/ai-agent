"""Profils de ranking (PRD §12.3, ADR-ADV-005 D7) — configuration versionnée.

Un profil = données pures : déclarations REQUIRED/OPTIONAL par composant +
paramètres de mapping/pénalité. Aucune logique métier ici (elle vit dans
`components.py`). Chargé depuis `configs/advisor/ranking_profiles.json`."""

from __future__ import annotations

import json
import pathlib
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

REQUIRED = "REQUIRED"
OPTIONAL = "OPTIONAL"

_CONFIG_PATH = (
    pathlib.Path(__file__).resolve().parents[5]
    / "configs" / "advisor" / "ranking_profiles.json"
)


@dataclass(frozen=True)
class RankingProfile:
    name: str
    requirements: Mapping[str, str]        # composant -> "REQUIRED" | "OPTIONAL"
    ev_floor: Decimal
    ev_cap: Decimal
    supported_baseline: Decimal
    liquidity_unknown_default: Decimal
    uncertainty_weight: Decimal
    concentration_weight: Decimal
    #: 0 = la probabilité n'entre pas dans le score (comportement d'avant),
    #: 1 = le score est directement proportionnel à la borne basse.
    probability_weight: Decimal = Decimal("0")
    #: Sous ce seuil de borne basse, un candidat n'est pas proposé du tout.
    min_probability: Decimal = Decimal("0")

    def requires(self, component: str) -> bool:
        return self.requirements.get(component) == REQUIRED

    def __post_init__(self) -> None:
        if self.ev_cap <= self.ev_floor:
            raise ValueError(f"ev_cap doit être > ev_floor (profil {self.name})")
        for name in ("supported_baseline", "liquidity_unknown_default"):
            value = getattr(self, name)
            if not (Decimal(0) < value < Decimal(1)):
                raise ValueError(f"{name} doit être dans ]0,1[ (profil {self.name}), reçu {value}")
        for name in ("uncertainty_weight", "concentration_weight"):
            if getattr(self, name) < Decimal(0):
                raise ValueError(f"{name} doit être >= 0 (profil {self.name})")


def load_ranking_profiles(path: pathlib.Path = _CONFIG_PATH) -> Mapping[str, RankingProfile]:
    data = json.loads(path.read_text(encoding="utf-8"))
    profiles: dict[str, RankingProfile] = {}
    for name, spec in data["profiles"].items():
        p = spec["params"]
        profiles[name] = RankingProfile(
            name=name,
            requirements=dict(spec["requirements"]),
            ev_floor=Decimal(p["ev_floor"]),
            ev_cap=Decimal(p["ev_cap"]),
            supported_baseline=Decimal(p["supported_baseline"]),
            liquidity_unknown_default=Decimal(p["liquidity_unknown_default"]),
            uncertainty_weight=Decimal(p["uncertainty_weight"]),
            concentration_weight=Decimal(p["concentration_weight"]),
            probability_weight=Decimal(p.get("probability_weight", "0")),
            min_probability=Decimal(p.get("min_probability", "0")),
        )
    return profiles
