"""Configuration versionnée du Combo Builder (Lot 9). Nouveau seuil métier
`min_combo_ev`, DISTINCT des seuils Eligibility (Lot 4) et Ranking (Lot 5).
Aucun seuil codé en dur. Checksum validé (intégrité pour audit/replay)."""

from __future__ import annotations

import hashlib
import json
import pathlib
from dataclasses import dataclass
from decimal import Decimal

from ..domain.money import ZERO, ONE

_CONFIG_PATH = (
    pathlib.Path(__file__).resolve().parents[5]
    / "configs" / "advisor" / "combo_policy.json"
)

# Champs entrant dans le checksum (identité de configuration, hors métadonnées).
_CHECKSUM_FIELDS = ("config_version", "effective_from", "top_k", "max_combo_legs",
                    "safety_margin", "min_combo_ev")


@dataclass(frozen=True)
class ComboPolicy:
    config_version: str
    effective_from: str
    checksum: str
    top_k: int
    max_combo_legs: int
    safety_margin: Decimal
    min_combo_ev: Decimal

    def __post_init__(self) -> None:
        if not (ZERO < self.safety_margin < ONE):
            raise ValueError(f"safety_margin doit être dans ]0,1[, reçu {self.safety_margin}")
        if self.top_k <= 0:
            raise ValueError("top_k doit être > 0")
        if self.max_combo_legs != 2:
            raise ValueError("V1 : max_combo_legs doit valoir 2 (3 legs différé)")


def _expected_checksum(data: dict) -> str:
    payload = {k: data[k] for k in _CHECKSUM_FIELDS}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def load_combo_policy(path: pathlib.Path = _CONFIG_PATH) -> ComboPolicy:
    data = json.loads(path.read_text(encoding="utf-8"))
    for field in (*_CHECKSUM_FIELDS, "checksum"):
        if field not in data:
            raise ValueError(f"clé de configuration combo manquante : {field}")
    if data["checksum"] != _expected_checksum(data):
        raise ValueError("checksum de configuration combo invalide (intégrité)")
    return ComboPolicy(
        config_version=data["config_version"], effective_from=data["effective_from"],
        checksum=data["checksum"], top_k=int(data["top_k"]),
        max_combo_legs=int(data["max_combo_legs"]),
        safety_margin=Decimal(data["safety_margin"]), min_combo_ev=Decimal(data["min_combo_ev"]))
