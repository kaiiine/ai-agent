"""Politique de décision BET/ABSTAIN versionnée (BE-FR-012, ADR-BE-003).

Externalise les seuils de décision du money-path (« non fixés ici, à calibrer »,
PRD-BE §Q3) dans un fichier versionné à checksum. Le Betting Engine DÉCIDE, il ne
SIZE PAS : aucune somme monétaire ici, donc pas de Decimal monétaire — le contrat
économique BE (cotes/proba/EV) est en `float`, la sécurité Decimal vit à la
frontière de sizing Advisor (ADR-ADV-007).
"""

from __future__ import annotations

import functools
import hashlib
import json
import pathlib
from dataclasses import dataclass

_CONFIG_PATH = (
    pathlib.Path(__file__).resolve().parents[5]
    / "configs" / "betting_engine" / "bet_decision_policy.json"
)
_CHECKSUM_FIELDS = (
    "config_version",
    "effective_from",
    "min_bet_ev",
    "min_data_quality",
    "min_model_reliability",
    "supported_model_reliability",
)


@dataclass(frozen=True)
class BetDecisionPolicy:
    config_version: str
    effective_from: str
    checksum: str
    min_bet_ev: float                    # seuil sur worst_case_ev (borne basse, BE-FR-012)
    min_data_quality: float
    min_model_reliability: float
    supported_model_reliability: float   # reliability V1 explicite d'un modèle SUPPORTED (§7)


def _expected_checksum(data: dict) -> str:
    payload = {k: data[k] for k in _CHECKSUM_FIELDS}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _in_unit_interval(x: float) -> bool:
    return 0.0 <= x <= 1.0


def load_bet_decision_policy(path: pathlib.Path = _CONFIG_PATH) -> BetDecisionPolicy:
    data = json.loads(path.read_text(encoding="utf-8"))
    for field in (*_CHECKSUM_FIELDS, "checksum"):
        if field not in data:
            raise ValueError(f"clé de configuration bet_decision manquante : {field}")
    if data["checksum"] != _expected_checksum(data):
        raise ValueError("checksum de configuration bet_decision invalide")
    # reliability / data_quality vivent dans [0,1] ; une valeur hors bornes est un
    # contrat cassé, jamais réparée en silence.
    for field in ("min_data_quality", "min_model_reliability", "supported_model_reliability"):
        if not _in_unit_interval(data[field]):
            raise ValueError(f"{field} doit être dans [0,1] (reçu {data[field]!r})")
    return BetDecisionPolicy(
        config_version=data["config_version"],
        effective_from=data["effective_from"],
        checksum=data["checksum"],
        min_bet_ev=float(data["min_bet_ev"]),
        min_data_quality=float(data["min_data_quality"]),
        min_model_reliability=float(data["min_model_reliability"]),
        supported_model_reliability=float(data["supported_model_reliability"]),
    )


@functools.lru_cache(maxsize=1)
def default_bet_decision_policy() -> BetDecisionPolicy:
    """Politique par défaut du processus (chargée une fois). Les tests qui veulent
    d'autres seuils passent une instance explicite, jamais ce singleton."""
    return load_bet_decision_policy()
