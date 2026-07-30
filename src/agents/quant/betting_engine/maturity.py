"""Maturité modèle : le passage EXPERIMENTAL -> SUPPORTED est une CONSÉQUENCE
MÉCANIQUE de critères mesurables (PRD-BE §7.1 : « Aucun MarketModel n'est
considéré SUPPORTED sans historique de calibration walk-forward documenté »).

Ce module NE calcule aucune métrique et NE lit aucune donnée : il reçoit des
observations déjà mesurées (issues du walk-forward hors échantillon + statut CLV +
statut freshness) et applique la politique versionnée. Un `ModelSupportDecision`
n'est donc jamais une déclaration : c'est la sortie déterministe d'un verdict.

Règle de verdict : SUPPORTED si et seulement si TOUS les critères requis sont
`PASS`. Le moindre `FAIL` ou `NOT_MEASURABLE` sur un critère requis -> EXPERIMENTAL.
Jamais de promotion « pour faire passer le produit ». Une absence de mesure (CLV
non mesurable) n'est jamais convertie en valeur favorable.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

_CONFIG_PATH = (
    pathlib.Path(__file__).resolve().parents[4]
    / "configs" / "betting_engine" / "model_maturity_policy.json"
)
_CHECKSUM_FIELDS = ("config_version", "effective_from", "criteria", "required_for_support")

# Statuts explicites de mesure de la CLV / freshness — jamais un nombre par défaut.
CLV_MEASURABLE = "MEASURABLE"
CLV_NOT_YET_MEASURABLE = "NOT_YET_MEASURABLE"
FRESHNESS_MEASURABLE = "MEASURABLE"
FRESHNESS_NOT_MEASURABLE = "NOT_MEASURABLE"


class Verdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_MEASURABLE = "NOT_MEASURABLE"


@dataclass(frozen=True)
class MaturityPolicy:
    config_version: str
    effective_from: str
    checksum: str
    criteria: dict
    required_for_support: dict          # {nom_critère: bool} — l'absence de mesure bloque-t-elle ?

    def threshold(self, name: str):
        return self.criteria[name]

    def is_required(self, name: str) -> bool:
        """Un critère absent du mapping est REQUIS par défaut (fail-safe : on ne
        rend jamais un critère optionnel par omission)."""
        return bool(self.required_for_support.get(name, True))


@dataclass(frozen=True)
class CriterionResult:
    name: str
    required: bool
    threshold: object          # seuil issu de la config (ou None)
    observed: object           # valeur observée (None si non mesurable)
    verdict: Verdict
    detail: str


@dataclass(frozen=True)
class ModelSupportDecision:
    model_name: str
    model_version: str
    status: str                # "SUPPORTED" | "EXPERIMENTAL"
    policy_version: str
    policy_checksum: str
    criteria: tuple[CriterionResult, ...]
    rationale: str
    assessed_at: str

    @property
    def is_supported(self) -> bool:
        return self.status == "SUPPORTED"


@dataclass(frozen=True)
class MaturityObservations:
    """Observations mesurées passées au verdict. Aucune n'est fabriquée ici."""
    n_evaluated: int
    n_temporal_folds: int
    calibration_error: float | None      # ECE hors échantillon (None si non mesurée)
    model_brier: float | None
    best_baseline_brier: float | None
    data_coverage: float | None          # n_evaluated / n_total_catalogue
    mean_data_quality: float | None
    fold_brier_spread: float | None      # max-min du Brier par fold (stabilité)
    clv_status: str                      # CLV_MEASURABLE | CLV_NOT_YET_MEASURABLE
    clv_mean: float | None               # renseigné seulement si clv_status == MEASURABLE
    live_freshness_status: str           # FRESHNESS_MEASURABLE | FRESHNESS_NOT_MEASURABLE


def _expected_checksum(data: dict) -> str:
    payload = {k: data[k] for k in _CHECKSUM_FIELDS}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def load_maturity_policy(path: pathlib.Path = _CONFIG_PATH) -> MaturityPolicy:
    data = json.loads(path.read_text(encoding="utf-8"))
    for field in (*_CHECKSUM_FIELDS, "checksum"):
        if field not in data:
            raise ValueError(f"clé de configuration maturité manquante : {field}")
    if data["checksum"] != _expected_checksum(data):
        raise ValueError("checksum de configuration maturité invalide")
    return MaturityPolicy(
        config_version=data["config_version"],
        effective_from=data["effective_from"],
        checksum=data["checksum"],
        criteria=dict(data["criteria"]),
        required_for_support=dict(data["required_for_support"]),
    )


def _min_criterion(name, required, observed, threshold, unit=""):
    """observed >= threshold -> PASS ; observed None -> NOT_MEASURABLE."""
    if observed is None:
        return CriterionResult(name, required, threshold, None, Verdict.NOT_MEASURABLE,
                               f"{name} non mesuré")
    verdict = Verdict.PASS if observed >= threshold else Verdict.FAIL
    return CriterionResult(name, required, threshold, observed, verdict,
                           f"observé {observed}{unit} vs min {threshold}{unit}")


def _max_criterion(name, required, observed, threshold, unit=""):
    """observed <= threshold -> PASS ; observed None -> NOT_MEASURABLE."""
    if observed is None:
        return CriterionResult(name, required, threshold, None, Verdict.NOT_MEASURABLE,
                               f"{name} non mesuré")
    verdict = Verdict.PASS if observed <= threshold else Verdict.FAIL
    return CriterionResult(name, required, threshold, observed, verdict,
                           f"observé {observed}{unit} vs max {threshold}{unit}")


def evaluate_maturity(
    *,
    model_name: str,
    model_version: str,
    observations: MaturityObservations,
    policy: MaturityPolicy,
) -> ModelSupportDecision:
    """Sépare STRICTEMENT deux notions (ADR-BE-001) :
      - l'ÉTAT DE MESURE d'un critère : PASS / FAIL / NOT_MEASURABLE ;
      - son caractère BLOQUANT : `policy.is_required(name)` (required_for_support).
    Un critère non requis (monitoring) est reporté mais ne bloque JAMAIS, même
    NOT_MEASURABLE ou FAIL. Un critère requis bloque dès qu'il n'est pas PASS.
    """
    c = policy.criteria
    o = observations
    req = policy.is_required
    results: list[CriterionResult] = []

    results.append(_min_criterion("min_sample_size", req("min_sample_size"), o.n_evaluated, c["min_sample_size"]))
    results.append(_min_criterion("min_temporal_folds", req("min_temporal_folds"), o.n_temporal_folds, c["min_temporal_folds"]))
    results.append(_max_criterion("max_calibration_error", req("max_calibration_error"), o.calibration_error, c["max_calibration_error"]))

    # Benchmark RELATIF : le modèle doit battre la meilleure baseline (Brier plus bas).
    if c.get("must_beat_baselines"):
        if o.model_brier is None or o.best_baseline_brier is None:
            results.append(CriterionResult("must_beat_baselines", req("must_beat_baselines"),
                                           "model<baseline", None, Verdict.NOT_MEASURABLE,
                                           "Brier modèle/baseline non mesuré"))
        else:
            beats = o.model_brier < o.best_baseline_brier
            results.append(CriterionResult(
                "must_beat_baselines", req("must_beat_baselines"), "model_brier < best_baseline_brier",
                {"model": o.model_brier, "best_baseline": o.best_baseline_brier},
                Verdict.PASS if beats else Verdict.FAIL,
                f"Brier modèle {o.model_brier} vs meilleure baseline {o.best_baseline_brier}"))

    results.append(_min_criterion("min_data_coverage", req("min_data_coverage"), o.data_coverage, c["min_data_coverage"]))
    results.append(_min_criterion("min_data_quality", req("min_data_quality"), o.mean_data_quality, c["min_data_quality"]))
    results.append(_max_criterion("max_fold_brier_spread", req("max_fold_brier_spread"), o.fold_brier_spread, c["max_fold_brier_spread"]))

    # CLV : Definition of Done PRD-BE ('CLV positif en moyenne'). NON mesurable
    # (aucun odds_history ouverture->clôture) -> NOT_MEASURABLE, jamais CLV=0.
    # Requis en V1 (required_for_support.positive_clv) : absence != CLV positive.
    if o.clv_status != CLV_MEASURABLE:
        results.append(CriterionResult("positive_clv", req("positive_clv"), "> 0", None,
                                       Verdict.NOT_MEASURABLE,
                                       f"CLV {o.clv_status} (aucune paire décision/clôture)"))
    else:
        results.append(CriterionResult(
            "positive_clv", req("positive_clv"), "> 0", o.clv_mean,
            Verdict.PASS if (o.clv_mean is not None and o.clv_mean > 0) else Verdict.FAIL,
            f"CLV moyenne observée {o.clv_mean}"))

    # Freshness mesurée au point de décision live (câblée Gateway->BE).
    if o.live_freshness_status != FRESHNESS_MEASURABLE:
        results.append(CriterionResult("measurable_live_freshness", req("measurable_live_freshness"),
                                       "MEASURABLE", None, Verdict.NOT_MEASURABLE,
                                       f"freshness live {o.live_freshness_status}"))
    else:
        results.append(CriterionResult("measurable_live_freshness", req("measurable_live_freshness"),
                                       "MEASURABLE", FRESHNESS_MEASURABLE, Verdict.PASS,
                                       "freshness live exposée (Gateway->BE)"))

    # BLOCAGE = critères REQUIS uniquement. Le monitoring (required=False) est
    # reporté mais n'entre jamais dans le verdict.
    required = [r for r in results if r.required]
    supported = all(r.verdict is Verdict.PASS for r in required)
    status = "SUPPORTED" if supported else "EXPERIMENTAL"

    rationale = (
        "tous les critères requis PASS -> SUPPORTED"
        if supported
        else "EXPERIMENTAL : critère(s) requis non satisfait(s) -> " + ", ".join(
            f"{r.name}={r.verdict.value}" for r in required if r.verdict is not Verdict.PASS)
    )

    return ModelSupportDecision(
        model_name=model_name,
        model_version=model_version,
        status=status,
        policy_version=policy.config_version,
        policy_checksum=policy.checksum,
        criteria=tuple(results),
        rationale=rationale,
        assessed_at=datetime.now(timezone.utc).isoformat(),
    )
