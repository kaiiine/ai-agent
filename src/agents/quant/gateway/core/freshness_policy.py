"""Politique de fraîcheur versionnée (GW-NFR-003).

Sort les demi-vies de fraîcheur et la tolérance de staleness live de leur codage
en dur historique (`core/quality.py`, `live_evaluation.py`) vers un fichier
versionné (`configs/gateway/freshness_policy.json`), avec les mêmes garanties que
les configs Advisor (checksum sha256 sur les champs métier). Les VALEURS sont
identiques à celles codées en dur auparavant : ce module ne change aucun nombre,
il rend seulement les seuils inspectables et versionnés.

La FORMULE de fraîcheur ne vit pas ici (elle reste dans `quality.py`) ; seuls ses
paramètres sont externalisés. Le chargement est mis en cache (une lecture par
processus) pour rester déterministe sans coûter un I/O par appel.
"""

from __future__ import annotations

import functools
import hashlib
import json
import pathlib
from dataclasses import dataclass
from datetime import timedelta

_CONFIG_PATH = (
    pathlib.Path(__file__).resolve().parents[5]
    / "configs" / "gateway" / "freshness_policy.json"
)
_CHECKSUM_FIELDS = (
    "config_version",
    "effective_from",
    "half_life_hours",
    "default_half_life_hours",
    "live_staleness_tolerance_hours",
)


@dataclass(frozen=True)
class FreshnessPolicy:
    config_version: str
    effective_from: str
    checksum: str
    half_life_hours: dict[str, float]
    default_half_life_hours: float
    live_staleness_tolerance_hours: float

    def half_life_for(self, data_type: str) -> float:
        """Demi-vie du data_type, défaut prudent si inconnu (jamais fabriqué)."""
        return self.half_life_hours.get(data_type, self.default_half_life_hours)

    @property
    def live_staleness_tolerance(self) -> timedelta:
        return timedelta(hours=self.live_staleness_tolerance_hours)


def _expected_checksum(data: dict) -> str:
    payload = {k: data[k] for k in _CHECKSUM_FIELDS}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def load_freshness_policy(path: pathlib.Path = _CONFIG_PATH) -> FreshnessPolicy:
    data = json.loads(path.read_text(encoding="utf-8"))
    for field in (*_CHECKSUM_FIELDS, "checksum"):
        if field not in data:
            raise ValueError(f"clé de configuration freshness manquante : {field}")
    if data["checksum"] != _expected_checksum(data):
        raise ValueError("checksum de configuration freshness invalide")
    # Les demi-vies sont des heures strictement positives : une valeur ≤ 0
    # ferait diverger 0.5 ** (age / half_life) — refus explicite, jamais un score fabriqué.
    for dt, hl in data["half_life_hours"].items():
        if not isinstance(hl, (int, float)) or hl <= 0:
            raise ValueError(f"half_life_hours[{dt}] doit être > 0 (reçu {hl!r})")
    if data["default_half_life_hours"] <= 0:
        raise ValueError("default_half_life_hours doit être > 0")
    if data["live_staleness_tolerance_hours"] <= 0:
        raise ValueError("live_staleness_tolerance_hours doit être > 0")
    return FreshnessPolicy(
        config_version=data["config_version"],
        effective_from=data["effective_from"],
        checksum=data["checksum"],
        half_life_hours=dict(data["half_life_hours"]),
        default_half_life_hours=float(data["default_half_life_hours"]),
        live_staleness_tolerance_hours=float(data["live_staleness_tolerance_hours"]),
    )


@functools.lru_cache(maxsize=1)
def default_freshness_policy() -> FreshnessPolicy:
    """Politique par défaut du processus (chargée une fois). Les tests qui veulent
    une autre politique passent une instance explicite, jamais ce singleton."""
    return load_freshness_policy()
