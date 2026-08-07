"""Batch de domaine — scanne un catalogue bookmaker puis évalue chaque événement
supporté à un UNIQUE `decision_time`.

FRONTIÈRE DE DOMAINE PUBLIQUE : c'est le seul contrat que consomment le CLI
(adaptateur) ET le futur adaptateur Advisor.

    CLI              -> evaluate_live_batch  (domaine)
    adaptateur Advisor -> evaluate_live_batch  (domaine)

Ce module n'importe AUCUNE couche d'interface (ni `cli`, ni `argparse`, ni
rendu) : l'Advisor peut en dépendre sans jamais importer `cli.py`. Le sens
inverse (le domaine ignore l'interface) est verrouillé par un test AST.

`decision_time` est capturé UNE fois, APRÈS le scan — cohérent avec
l'orchestrateur mono-événement (`as_of == point_in_time == decision_time`,
jamais `now()` dans la couche métier). Un échec inattendu sur UN événement
n'arrête pas le batch : il devient un résultat typé `GATEWAY_UNAVAILABLE`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from .bookmakers.protocol import RawBookmakerEvent
from .bookmakers.winamax.catalogue import multisport_events
from .live_evaluation import (
    LiveEvaluationResult,
    LiveEvaluationStatus,
    evaluate_live_event,
)

# Un événement scanné apparié à son évaluation. `tuple` (et non `list`) : le
# batch est un instantané immuable de la frontière.
EvaluatedEvent = tuple[RawBookmakerEvent, LiveEvaluationResult]


@dataclass(frozen=True)
class LiveEvaluationBatch:
    decision_time: datetime
    results: tuple[EvaluatedEvent, ...]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _catalogue_multisport(connector) -> list[RawBookmakerEvent]:
    """Les sports ENREGISTRÉS, lus au registre plutôt qu'écrits ici : ajouter un
    module sportif suffit à le faire scanner."""
    from .sports.registry import SPORT_MODULES

    return list(multisport_events(connector, sorted(SPORT_MODULES)))


def evaluate_live_batch(
    connector,
    *,
    sports_gateway,
    event_resolver,
    catalogue: Callable = _catalogue_multisport,
    evaluate: Callable = evaluate_live_event,
    now_fn: Callable[[], datetime] = _utcnow,
) -> LiveEvaluationBatch:
    """Cœur de domaine testable. `catalogue(connector)` peut lever (scan échoué)
    -> propagé à l'appelant (le CLI le mappe sur son code de sortie). Un échec
    inattendu sur UN événement n'arrête pas le batch (résultat typé).

    Le catalogue par défaut couvre les SEPT sports enregistrés. Il valait
    `supported_events`, dont le sport valait lui-même « football » : un appelant
    qui ne précisait rien croyait scanner le produit et scannait un sport. Le
    défaut d'une fonction générique doit être générique, sinon il choisit à la
    place de l'appelant sans que l'appel le montre."""
    events = catalogue(connector)                       # scan ; propage l'échec
    decision_time = now_fn()                            # capturé UNE fois, APRÈS le scan

    results: list[EvaluatedEvent] = []
    for event in events:
        try:
            result = evaluate(
                event, decision_time=decision_time,
                event_resolver=event_resolver, sports_gateway=sports_gateway,
            )
        except Exception as exc:                        # défensif : un événement ne fait pas tomber le batch
            result = LiveEvaluationResult(
                status=LiveEvaluationStatus.GATEWAY_UNAVAILABLE,
                reason=f"erreur technique inattendue : {type(exc).__name__}",
                decision_time=decision_time, bookmaker_event_id=event.bookmaker_event_id,
                error_context={"type": type(exc).__name__, "repr": repr(exc)},
            )
        results.append((event, result))
    return LiveEvaluationBatch(decision_time, tuple(results))
