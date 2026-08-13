"""La garde qui empêche le passé de contenir l'avenir.

C'est la panne la plus coûteuse du domaine, parce qu'elle ne ressemble pas à une
panne : un modèle qui a vu le résultat obtient d'excellentes métriques, franchit
les critères de maturité, et perd de l'argent en production. Rien dans le
benchmark ne le signale — le benchmark est justement ce qui a été contaminé.

TROIS TEMPS, JAMAIS DEUX. `prediction_time` (quand on décide),
`historical_event_time` (quand la rencontre a eu lieu) et
`observed_source_timestamp` (quand la source l'a publiée). Les deux premiers
suffisent pour un RÉSULTAT : un match joué avant la décision était connaissable.
Ils ne suffisent pas pour un CLASSEMENT ou une COTE, qui ont leur propre date de
validité — un classement final de saison est antérieur à aucune des journées
qu'il résume.

D'où une garde qui distingue par `data_type` au lieu d'appliquer partout la même
comparaison. Une règle unique serait soit trop laxiste pour les classements,
soit trop stricte pour les résultats.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

#: Natures dont la seule date d'événement suffit : l'observation est un FAIT
#: daté, connaissable dès qu'il s'est produit.
_FAITS_DATES = frozenset({"matches", "results"})

#: Natures qui portent un état À UNE DATE, et dont la date de publication fait
#: partie de la validité. Les traiter comme des faits datés ferait entrer un
#: classement de fin de saison dans la prédiction de la 3ᵉ journée.
_ETATS_DATES = frozenset({"rankings", "odds", "lineups"})


class LeakageError(ValueError):
    """Levée plutôt que rendue : une fuite ne se rattrape pas, elle s'arrête."""


@dataclass(frozen=True)
class LeakVerdict:
    admissible: bool
    raison: str
    detail: str = ""

    def __bool__(self) -> bool:
        return self.admissible


def verifier_admissibilite(
    *,
    prediction_time: datetime,
    historical_event_time: datetime,
    data_type: str,
    observed_source_timestamp: datetime | None = None,
) -> LeakVerdict:
    """Cette observation était-elle connaissable au moment de la décision ?

    STRICTEMENT antérieur, jamais « antérieur ou égal » : deux rencontres au même
    horodatage sont simultanées, et l'une ne peut pas informer l'autre. La règle
    reprend exactement celle du `PointInTimeGateway` (`kickoff < cutoff`) — deux
    gardes qui divergeraient laisseraient passer ce que l'autre bloque.
    """
    if prediction_time.tzinfo is None or historical_event_time.tzinfo is None:
        raise LeakageError(
            "comparaison temporelle sans fuseau : l'ordre ne serait pas défini")

    if historical_event_time >= prediction_time:
        return LeakVerdict(
            False, "FUTURE_EVENT",
            f"événement {historical_event_time.isoformat()} "
            f">= décision {prediction_time.isoformat()}")

    if data_type in _ETATS_DATES:
        if observed_source_timestamp is None:
            return LeakVerdict(
                False, "SOURCE_TIMESTAMP_REQUIRED",
                f"{data_type} porte un état daté : sans date de publication, "
                "impossible de prouver qu'il ne résume pas l'avenir")
        if observed_source_timestamp.tzinfo is None:
            raise LeakageError("observed_source_timestamp sans fuseau")
        if observed_source_timestamp >= prediction_time:
            return LeakVerdict(
                False, "SOURCE_PUBLISHED_AFTER_DECISION",
                f"publié {observed_source_timestamp.isoformat()} "
                f">= décision {prediction_time.isoformat()}")

    elif data_type not in _FAITS_DATES:
        # Une nature inconnue est refusée, pas devinée : c'est la seule réponse
        # qui ne peut pas laisser passer une fuite qu'on n'a pas su qualifier.
        return LeakVerdict(False, "UNKNOWN_DATA_TYPE",
                           f"nature {data_type!r} sans règle temporelle")

    return LeakVerdict(True, "OK")


def filtrer_admissibles(evidences, *, prediction_time: datetime, data_type: str):
    """`(retenues, {raison: compte})`. Ce qui est écarté est COMPTÉ, pas oublié —
    un filtre silencieux masquerait un corpus vide derrière un run réussi."""
    retenues, rejets = [], {}
    for e in evidences:
        v = verifier_admissibilite(
            prediction_time=prediction_time,
            historical_event_time=e.scheduled_at,
            data_type=data_type,
            observed_source_timestamp=e.observed_source_timestamp)
        if v.admissible:
            retenues.append(e)
        else:
            rejets[v.raison] = rejets.get(v.raison, 0) + 1
    return retenues, rejets
