"""Registre d'expériences — append-only, reproductible (PRD §7.2).

Un `ExperimentResult` par ligne JSON, jamais muté. La reproductibilité vient de
`code_revision` + `dataset_fingerprint` + `parameters` + `point_in_time_policy` +
`feature_schema_version` : re-jouer le même code sur le même dataset redonne les
mêmes métriques. Les conventions de métriques sont portées PAR le champ `metrics`
(cf. metrics.py), donc stockées ici aussi.

Ce module ne touche JAMAIS le manifest, le statut d'un modèle, `DataReadiness` ni
BE-FR-011 : `ExperimentResult` ≠ `ModelSupportDecision`. Un résultat ne peut pas
porter `experiment_status = "SUPPORTED"` (rejeté) — le support est une décision
explicite, séparée, ultérieure.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# `SUPPORTED` est structurellement interdit ici : ce n'est pas une décision de
# support, seulement un résultat expérimental.
_FORBIDDEN_STATUS = {"SUPPORTED"}
_ALLOWED_STATUS = {"COMPLETED", "CANDIDATE_FOR_REVIEW", "FAILED"}


@dataclass(frozen=True)
class ExperimentResult:
    experiment_id: str
    model_name: str
    model_version: str
    code_revision: str
    dataset_fingerprint: str
    feature_schema_version: str
    evaluation_start: str                 # ISO 8601 — début de la fenêtre évaluée
    evaluation_end: str
    point_in_time_policy: str             # ex. "strict_prior_only"
    window_strategy: str                  # ex. "expanding"
    parameters: dict                      # rho, shrinkage_k, home_advantage... (figés)
    n_events_total: int
    n_events_evaluated: int
    n_events_excluded: int
    exclusion_reasons: dict               # {raison: compte}
    metrics: dict                         # auto-descriptif (conventions incluses)
    experiment_status: str                # jamais "SUPPORTED"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self) -> None:
        if self.experiment_status in _FORBIDDEN_STATUS:
            raise ValueError(
                f"experiment_status={self.experiment_status!r} interdit : un ExperimentResult "
                "n'est pas une décision de support (ModelSupportDecision, séparée)"
            )
        if self.experiment_status not in _ALLOWED_STATUS:
            raise ValueError(
                f"experiment_status={self.experiment_status!r} invalide "
                f"(attendu {sorted(_ALLOWED_STATUS)})"
            )


def new_experiment_id() -> str:
    return f"exp-{uuid.uuid4().hex[:12]}"


def dataset_fingerprint(data: bytes) -> str:
    """SHA-256 du dataset brut — ancre la reproductibilité à la donnée exacte."""
    return "sha256:" + hashlib.sha256(data).hexdigest()


def current_code_revision() -> str:
    """SHA git courant, ou 'unknown' hors dépôt."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def append_experiment(result: ExperimentResult, path: Path) -> None:
    """Ajoute un résultat en fin de fichier (append-only, jamais de réécriture)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(result), ensure_ascii=False) + "\n")


def load_experiments(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]
