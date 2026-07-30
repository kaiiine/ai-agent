"""Primitive de sizing V1 d'une ligne SINGLE (ADR-ADV-007). RÉUTILISÉE par le
Portfolio Optimizer (Lot 8) — jamais une 2ᵉ formule.

Kelly sur la probabilité PRUDENTE (`probability_low`, imposé par le contrat) ;
atténué par `fractional_kelly` (config) × `reliability` × `data_quality` ; borné
par les seuls plafonds présents (un `None` n'est jamais un plafond à 0)."""

from __future__ import annotations

import hashlib
import json
import pathlib
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_DOWN, Context, Decimal

from ..domain.candidates import CandidateBet
from ..domain.money import ONE, ZERO

# Précision de CALCUL déterministe pour les divisions. Pas un arrondi métier
# (granularité de mise -> Lot 8 / ADR-ADV-002). Le cap `max_payout/odds` arrondit
# vers le BAS pour garantir `stake·odds <= max_payout` (jamais dépassé).
_DIV = Context(prec=28)
_DIV_FLOOR = Context(prec=28, rounding=ROUND_DOWN)

_CONFIG_PATH = (
    pathlib.Path(__file__).resolve().parents[5]
    / "configs" / "advisor" / "sizing_policy.json"
)
_CHECKSUM_FIELDS = ("config_version", "effective_from", "profiles")


@dataclass(frozen=True)
class SizingProfile:
    fractional_kelly: Decimal
    per_line_cap_fraction: Decimal
    # Équivalents COMBO (ADR-ADV-014), plus conservateurs. Défaut None : un profil
    # construit sans paramètres combo ne peut pas sizer un combo (garde explicite).
    combo_fractional_kelly: Decimal | None = None
    combo_line_cap_fraction: Decimal | None = None


def _expected_checksum(data: dict) -> str:
    payload = {k: data[k] for k in _CHECKSUM_FIELDS}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def load_sizing_profiles(path: pathlib.Path = _CONFIG_PATH) -> Mapping[str, SizingProfile]:
    data = json.loads(path.read_text(encoding="utf-8"))
    for field in (*_CHECKSUM_FIELDS, "checksum"):
        if field not in data:
            raise ValueError(f"clé de configuration sizing manquante : {field}")
    if data["checksum"] != _expected_checksum(data):
        raise ValueError("checksum de configuration sizing invalide (intégrité money)")
    profiles: dict[str, SizingProfile] = {}
    for name, p in data["profiles"].items():
        fk = Decimal(p["fractional_kelly"])
        cap = Decimal(p["per_line_cap_fraction"])
        combo_fk = Decimal(p["combo_fractional_kelly"])
        combo_cap = Decimal(p["combo_line_cap_fraction"])
        # Invariant V1 (money) : le COMBO n'est jamais plus agressif que le SINGLE.
        if not (ZERO < combo_fk <= fk):
            raise ValueError(f"{name}: 0 < combo_fractional_kelly <= fractional_kelly requis")
        if not (ZERO < combo_cap <= cap):
            raise ValueError(f"{name}: 0 < combo_line_cap_fraction <= per_line_cap_fraction requis")
        profiles[name] = SizingProfile(
            fractional_kelly=fk, per_line_cap_fraction=cap,
            combo_fractional_kelly=combo_fk, combo_line_cap_fraction=combo_cap)
    return profiles


def kelly_fraction(probability_low: Decimal, bookmaker_odds: Decimal) -> Decimal:
    """`f* = (p·odds − 1)/(odds − 1)` sur la borne basse. <= 0 -> 0 (aucun edge
    prudent -> aucune mise, jamais une mise de compensation)."""
    numerator = probability_low * bookmaker_odds - ONE     # = expected_value_low
    if numerator <= ZERO:
        return ZERO
    return _DIV.divide(numerator, bookmaker_odds - ONE)


def compute_single_stake(
    candidate: CandidateBet, *, reliability: Decimal, bankroll: Decimal,
    max_total_stake: Decimal | None, sizing: SizingProfile,
) -> Decimal:
    """Mise d'une ligne SINGLE. `0` si non-SUPPORTED (BE-FR-011) ou Kelly <= 0."""
    if candidate.model_maturity != "SUPPORTED":
        return ZERO                                        # jamais de mise sur non-SUPPORTED
    kelly = kelly_fraction(candidate.probability_low, candidate.bookmaker_odds)
    if kelly <= ZERO:
        return ZERO

    raw_fraction = sizing.fractional_kelly * kelly * reliability * candidate.data_quality
    proposed = bankroll * raw_fraction

    # Plafonds : uniquement les présents (un None n'entre JAMAIS comme borne 0).
    caps = [proposed, bankroll, sizing.per_line_cap_fraction * bankroll]
    if max_total_stake is not None:
        caps.append(max_total_stake)
    if candidate.max_stake is not None:
        caps.append(candidate.max_stake)
    if candidate.max_payout is not None:
        caps.append(_DIV_FLOOR.divide(candidate.max_payout, candidate.bookmaker_odds))

    stake = min(caps)
    return stake if stake > ZERO else ZERO
