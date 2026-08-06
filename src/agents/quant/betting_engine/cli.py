"""CLI adaptateur — run ponctuel manuel : scan Winamax -> évaluations lisibles.

Adaptateur MINCE : ne connaît ni le PRELOADED_STATE, ni la canonicalisation, ni
la résolution, ni la décision. Il délègue tout le batch à la frontière de domaine
`evaluate_live_batch` (scan + évaluation), et ne garde QUE l'I/O : parsing
d'arguments, rendu, code de sortie. Aucune logique métier dupliquée, aucune
écriture ~/.axon, aucun scheduler.

Codes de sortie :
  0 = scan OK et au moins un résultat exploitable (vraie prédiction calculée) ;
  1 = échec global du scan ou erreur technique du CLI ;
  2 = scan OK mais AUCUN événement exploitable.
« Exploitable » = `LiveEvaluationResult.has_actionable_evaluation` (source unique).
"""

from __future__ import annotations

import argparse
import json
import sys

from .bookmakers.protocol import RawBookmakerEvent
from .live_batch import evaluate_live_batch
from .live_evaluation import LiveEvaluationResult


def exit_code_for(results) -> int:
    """0 si au moins un résultat exploitable, sinon 2 (scan supposé réussi)."""
    return 0 if any(res.has_actionable_evaluation for _, res in results) else 2


# ── Rendu (fonctions pures) ───────────────────────────────────────────────────
def _title(event: RawBookmakerEvent) -> str:
    return f"{event.slot_1_name} – {event.slot_2_name}"


def _warning_tags(result: LiveEvaluationResult) -> list[str]:
    seen: list[str] = list(result.warnings)
    for pred in result.predictions.values():
        seen.extend(pred.explanation.warnings)
    # dédup en conservant l'ordre, tronqué pour la lisibilité
    out: list[str] = []
    for w in seen:
        tag = w.split(":")[0].strip()[:40]
        if tag and tag not in out:
            out.append(tag)
    return out


def render_human(event: RawBookmakerEvent, result: LiveEvaluationResult) -> list[str]:
    """Deux lignes. Probabilités affichées UNIQUEMENT si une vraie prédiction
    existe ; sinon « Probabilities: unavailable » — jamais de fausse valeur."""
    if result.has_actionable_evaluation:
        reason = result.decisions[0].reasons[0] if result.decisions else "MODEL_NOT_SUPPORTED"
        # SCHÉMA-DRIVEN : issues réellement prédites (2-way OU 3-way), jamais home/draw/away figé.
        probs = " | ".join(
            f"{sel.capitalize()} {pred.fair_probability * 100:.1f}%"
            for sel, pred in result.predictions.items()
        )
        tags = ", ".join(_warning_tags(result)) or "none"
        return [f"{_title(event)} | ABSTAIN | {reason}",
                f"{probs} | warnings: {tags}"]
    return [f"{_title(event)} | ABSTAIN | {result.status.value}",
            f"Probabilities: unavailable | {result.reason}"]


def build_json_record(event: RawBookmakerEvent, result: LiveEvaluationResult) -> dict:
    actionable = result.has_actionable_evaluation
    return {
        "bookmaker_event_id": event.bookmaker_event_id,
        "slot_1": event.slot_1_name,
        "slot_2": event.slot_2_name,
        "status": result.status.value,
        "decision": "ABSTAIN" if actionable else None,
        "reason": (result.decisions[0].reasons[0] if actionable and result.decisions
                   else "MODEL_NOT_SUPPORTED") if actionable else result.reason,
        "probabilities": (
            {sel: round(pred.fair_probability, 4) for sel, pred in result.predictions.items()}
            if actionable else None
        ),
        "warnings": list(result.warnings),
    }


# ── I/O + code de sortie ──────────────────────────────────────────────────────
def main(argv: list[str] | None = None, *, connector=None, sports_gateway=None,
         event_resolver=None) -> int:
    parser = argparse.ArgumentParser(description="Évaluation live Winamax (run ponctuel).")
    parser.add_argument("--format", choices=("human", "json"), default="human")
    args = parser.parse_args(argv)

    # Câblage des dépendances réelles (injectables pour les tests).
    if connector is None:
        from .bookmakers.winamax.connector import WinamaxConnector
        connector = WinamaxConnector()
    if event_resolver is None:
        # Les SEPT sports, pas le seul football : le résolveur filtre par préfixe
        # d'identifiant, donc les espaces de noms restent étanches. Avec le seul
        # référentiel football, tout événement non-football était UNRESOLVED avant
        # même d'atteindre son modèle — pourtant enregistré et prêt.
        from .sports.registry import build_event_resolver
        event_resolver = build_event_resolver()
    if sports_gateway is None:
        from src.agents.quant.gateway import gateway as sports_gateway

    # Le catalogue par défaut (`supported_events`) scanne le FOOTBALL seul. Le run
    # live ne voyait donc jamais les six autres sports, et `multisport_events`
    # existait sans appelant. Chaque `RawBookmakerEvent` porte son sport : le
    # dispatch se fait en aval par `SPORT_MODULES`, sans aucun `if sport ==`.
    from .bookmakers.winamax.catalogue import multisport_events
    from .sports.registry import SPORT_MODULES
    sports = sorted(SPORT_MODULES)

    try:
        run = evaluate_live_batch(connector, sports_gateway=sports_gateway,
                                  event_resolver=event_resolver,
                                  catalogue=lambda c: multisport_events(c, sports))
    except Exception as exc:   # noqa: BLE001 — scan total / erreur technique -> code 1
        print(f"échec du scan / erreur technique : {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps([build_json_record(e, r) for e, r in run.results],
                         ensure_ascii=False, indent=2))
    else:
        print(f"# scan terminé, decision_time={run.decision_time.isoformat()} — "
              f"{len(run.results)} événement(s) supporté(s)")
        for event, result in run.results:
            for line in render_human(event, result):
                print(line)

    return exit_code_for(run.results)


if __name__ == "__main__":   # pragma: no cover
    raise SystemExit(main())
