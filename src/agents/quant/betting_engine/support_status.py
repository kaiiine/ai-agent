"""Statut de support DÉRIVÉ, jamais déclaratif (PRD-BE §7.1 / BE-FR-011).

Un modèle n'est `SUPPORTED` que si un `ModelSupportDecision` de statut SUPPORTED a
été PERSISTÉ dans le ledger append-only par le verdict mécanique (`maturity.py`).
En l'absence d'une telle entrée (cas actuel), le statut résolu est `EXPERIMENTAL`.

Ainsi `manifest.GLOBAL_MODEL_STATUS` et le plafond de readiness du modèle lisent la
MÊME source de vérité (le ledger), au lieu d'un littéral codé en dur. Le ledger par
défaut vit sous `var/` (gitignoré) ; absent -> EXPERIMENTAL sans aucune I/O de
lecture. Chemin injectable pour les tests.
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import asdict
from datetime import datetime, timezone

from .core.market_model import DataReadiness
from .maturity import CriterionResult, ModelSupportDecision

_DEFAULT_LEDGER = (
    pathlib.Path(__file__).resolve().parents[4]
    / "var" / "betting_engine" / "model_support_ledger.jsonl"
)


def _decision_to_jsonable(decision: ModelSupportDecision) -> dict:
    d = asdict(decision)
    d["criteria"] = [
        {**asdict(c), "verdict": c.verdict.value} for c in decision.criteria
    ]
    return d


def append_support_decision(
    decision: ModelSupportDecision, ledger_path: pathlib.Path | None = None
) -> None:
    """Persiste un verdict (append-only). Écrire un verdict EXPERIMENTAL est légitime
    et utile (trace de non-promotion) ; seul un verdict SUPPORTED persisté promeut."""
    path = pathlib.Path(ledger_path) if ledger_path is not None else _DEFAULT_LEDGER
    if "~/.axon" in str(path) or str(path).startswith("~"):
        raise ValueError("ledger de support : chemin ~/.axon interdit")
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"recorded_at": datetime.now(timezone.utc).isoformat(),
              "decision": _decision_to_jsonable(decision)}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")


def resolve_market_status(
    model_name: str,
    model_version: str,
    *,
    ledger_path: pathlib.Path | None = None,
) -> DataReadiness:
    """Statut courant DÉRIVÉ du ledger pour (model_name, model_version).

    SUPPORTED seulement si la DERNIÈRE décision persistée qui matche a le statut
    SUPPORTED. Sinon (aucune entrée, ou dernière entrée EXPERIMENTAL) -> EXPERIMENTAL.
    Jamais de fallback silencieux vers SUPPORTED.
    """
    path = pathlib.Path(ledger_path) if ledger_path is not None else _DEFAULT_LEDGER
    if not path.exists():
        return DataReadiness.EXPERIMENTAL                # aucune preuve persistée
    latest: str | None = None
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            dec = json.loads(line)["decision"]
            if dec["model_name"] == model_name and dec["model_version"] == model_version:
                latest = dec["status"]
    if latest == "SUPPORTED":
        return DataReadiness.SUPPORTED
    return DataReadiness.EXPERIMENTAL
