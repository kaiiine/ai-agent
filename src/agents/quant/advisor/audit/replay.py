"""Replay EXACT historique (Lot 10 §15/§16/§17). Reconstruit la décision à partir
des INPUTS ARCHIVÉS uniquement : requête, snapshots de config, batch adapté. Ne
consulte JAMAIS les configs courantes, ne rappelle ni bookmaker, ni Betting Engine
live, ni Gateway.

« Identique » = résultat MÉTIER déterministe (recommandation + trail Combo), pas
les métadonnées runtime (created_at, chemin de store, durée). Retourne un
`ReplayResult` structuré, exploitable hors tests (futur outil de diagnostic).

Hors scope V1 : COMPARE_CURRENT / drift analysis, migrations de schéma, replay
cross-version de code incompatible (le code capable de lire ce schéma doit exister)."""

from __future__ import annotations

import pathlib
import tempfile
from dataclasses import dataclass

from ..domain import serialization
from ..input_adapter.schema import adapted_batch_from_jsonable
from . import record, snapshots


@dataclass(frozen=True)
class ReplayResult:
    matches: bool
    differences: tuple[str, ...]


def _canon(obj) -> str:
    return serialization.to_json(obj)                    # objet OU dict : mêmes octets canoniques


def replay_exact(envelope: dict, *, run_pipeline_fn=None) -> ReplayResult:
    """`envelope` = enveloppe VALIDÉE (via `JsonlAuditStore.get`, qui a déjà
    vérifié version + checksum payload)."""
    payload = envelope["payload"]

    # Reconstruction des INPUTS depuis les archives (jamais l'état courant).
    request = serialization.request_from_jsonable(payload["request"])
    adapted_batch = adapted_batch_from_jsonable(payload["adapted_batch"])

    with tempfile.TemporaryDirectory() as tmp:
        configs = snapshots.reconstruct_configs(payload["config_snapshots"], pathlib.Path(tmp))
        if run_pipeline_fn is None:
            from ..pipeline import run_pipeline as run_pipeline_fn   # lazy : évite tout cycle
        fresh = run_pipeline_fn(adapted_batch, request, **configs)

    # Comparaison MÉTIER canonique COMPLÈTE (§16) : recommandation finale + TOUTES
    # les décisions intermédiaires déterministes (statuts, reason codes, scores,
    # ranking via policy/ranked evaluations) + trail Combo. Hors métadonnées runtime
    # (created_at/durée/chemin) qui ne font pas partie du résultat métier. Aucun
    # filtre opportuniste : tout champ métier divergent est exposé dans `differences`.
    checks = {
        "recommendation": (fresh.recommendation, payload["recommendation"]),
        "policy_evaluations": (tuple(fresh.trace.policy_evaluations), payload["policy_evaluations"]),
        "ranked_evaluations": (tuple(fresh.trace.ranked_evaluations), payload["ranked_evaluations"]),
        "combos": (record._combo_trail(fresh.trace), payload["combos"]),
    }
    differences = [name for name, (fresh_obj, archived) in checks.items()
                   if _canon(fresh_obj) != _canon(archived)]
    return ReplayResult(matches=not differences, differences=tuple(differences))
