"""Pont de décision betting STRUCTURÉ — **source de vérité UNIQUE** (reroute legacy).

Les tools conversationnels (`tools.py`) délèguent ICI. Aucune probabilité, EV, edge,
Kelly, proba jointe ou « value » n'est calculée dans cette couche ni dans les tools :
tout provient du Betting Engine (`evaluate_live_event` -> `evaluate_selection`) et,
pour le sizing, de l'Advisor canonique. Il n'existe donc plus de seconde pile de
décision (ADR : reroute D = REROUTE_VERS_STRUCTURE).

Invariants durs :
- **ABSTAIN structuré -> ABSTAIN outil.** Le cap BE-FR-011 (modèle non SUPPORTED ⇒
  jamais BET) traverse tel quel. Jamais « cette cote basse semble value ».
- **Jamais de fallback legacy** (`dixon_coles`/`ev_engine`/`probability_engine`).
- **Marché sans modèle structuré -> `MARKET_UNAVAILABLE`.** Le seul modèle est
  MATCH_WINNER (1X2) ; over/under/BTTS n'ont PAS de modèle structuré -> refus
  explicite (jamais une proba inventée par un moteur parallèle).
- **Localisation par identité canonique** (jamais un match flou décidant d'argent) :
  on résout les équipes demandées ET les événements du catalogue par le même
  résolveur, puis `evaluate_live_event` re-résout STRICTEMENT (gate money).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Sequence

from .betting_engine.bookmakers.protocol import RawBookmakerEvent
from .betting_engine.live_evaluation import (
    LiveEvaluationStatus,
    evaluate_live_event,
)

# Marchés du modèle structuré : UNIQUEMENT MATCH_WINNER (1X2). Alias bruts inclus.
# Tout autre marché (over/under, BTTS, …) n'a AUCUN modèle structuré -> refus.
_MARKET_TO_SELECTION: dict[str, str] = {
    "home": "home", "1": "home",
    "draw": "draw", "x": "draw", "n": "draw", "nul": "draw",
    "away": "away", "2": "away",
}

# Statuts de sortie (machine-readable, stables).
#
# Chaque cause de refus a SON code. Un « unsupported » générique force le lecteur —
# modèle ou humain — à deviner ce qu'il faut corriger, et il devine mal : une
# compétition non mappée présentée comme une équipe introuvable envoie vérifier
# l'orthographe d'un nom parfaitement correct. Les quatre causes ci-dessous sont
# indépendantes et se réparent à des endroits différents du système.
EVALUATED = "EVALUATED"                  # une BettingDecision structurée existe (BET ou ABSTAIN)
MARKET_UNAVAILABLE = "MARKET_UNAVAILABLE"    # marché hors modèle structuré (over/under/BTTS…)
IDENTITY_UNRESOLVED = "IDENTITY_UNRESOLVED"  # un PARTICIPANT ne résout pas -> identity_data.py
COMPETITION_UNRESOLVED = "COMPETITION_UNRESOLVED"    # tid bookmaker non mappé -> competition_mapping.py
PROVIDER_COVERAGE_MISSING = "PROVIDER_COVERAGE_MISSING"  # identités OK, aucun provider vérifié
EVENT_NOT_FOUND = "EVENT_NOT_FOUND"          # aucun événement du catalogue ne matche
MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"      # aucune capability de modèle pour ce sport/marché
INSUFFICIENT_FEATURES = "INSUFFICIENT_FEATURES"      # données présentes mais trop minces
DATA_UNAVAILABLE = "DATA_UNAVAILABLE"        # gateway indisponible (jamais supposé frais)

# Mapping LiveEvaluationStatus (non EVALUATED) -> statut de pont. TOUJOURS ABSTAIN.
_LIVE_STATUS_MAP: dict[LiveEvaluationStatus, str] = {
    LiveEvaluationStatus.SPORT_NOT_SUPPORTED: MODEL_UNAVAILABLE,
    LiveEvaluationStatus.COMPETITION_NOT_COVERED: PROVIDER_COVERAGE_MISSING,
    LiveEvaluationStatus.COMPETITION_NOT_RESOLVED: COMPETITION_UNRESOLVED,
    LiveEvaluationStatus.EVENT_NOT_RESOLVED: IDENTITY_UNRESOLVED,
    LiveEvaluationStatus.MARKET_CANONICALIZATION_FAILED: MARKET_UNAVAILABLE,
    LiveEvaluationStatus.GATEWAY_UNAVAILABLE: DATA_UNAVAILABLE,
    LiveEvaluationStatus.DATA_TOO_STALE: DATA_UNAVAILABLE,
    LiveEvaluationStatus.INSUFFICIENT_FEATURES: INSUFFICIENT_FEATURES,
}


@dataclass(frozen=True)
class SelectionDecision:
    """Décision structurée pour UNE sélection — 100 % dérivée d'`evaluate_selection`."""
    selection: str
    decision: str                              # "BET" | "ABSTAIN" (jamais BET hors SUPPORTED)
    bookmaker_odds: float | None
    fair_probability: float | None
    probability_interval: tuple[float, float] | None
    expected_value: float | None               # EV moyen (audit)
    worst_case_ev: float | None                # EV borne basse (BE-FR-012)
    no_vig_probability: float | None
    edge: float | None
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class MatchDecision:
    """Résultat structuré pour un match : statut + décisions par sélection (si évalué)."""
    status: str
    detail: str
    home_team: str
    away_team: str
    competition: str | None = None
    bookmaker: str | None = None
    selections: dict[str, SelectionDecision] = field(default_factory=dict)

    @property
    def evaluated(self) -> bool:
        return self.status == EVALUATED


# ── Dépendances par défaut (I/O réelle ; injectables pour tests hermétiques) ───
def _default_deps(sport: str = "football"):   # pragma: no cover (I/O réelle)
    """Dépendances réelles, RÉSOLUES POUR LE SPORT DEMANDÉ.

    L'identité était auparavant construite sur le référentiel football quel que
    soit le sport : les six autres sports étaient enregistrés et atteignables,
    mais échouaient tous en IDENTITY_UNRESOLVED avant d'atteindre leur modèle —
    un chemin football-spécifique caché sous une façade générique. Chaque sport
    a son espace de noms propre (`SportModule.known_entities`), et un joueur de
    tennis ne peut pas résoudre contre un club de football.
    """
    from .betting_engine.bookmakers.winamax.connector import WinamaxConnector
    from .betting_engine.bookmakers.winamax.catalogue import all_events
    from .betting_engine.bookmakers.bookmaker_registry import BookmakerEventResolver
    from .betting_engine.sports.registry import SPORT_MODULES
    from .gateway.core.identity_resolver import IdentityResolver
    from .gateway import gateway as sports_gateway

    module = SPORT_MODULES.get(sport)
    entities = list(module.known_entities()) if module else []
    identity = IdentityResolver(entities)

    def search(name: str) -> dict | None:
        hit = identity.find_by_name(name)
        return {"canonical_id": hit.canonical_id, "name": hit.canonical_name} if hit else None

    return dict(
        connector=WinamaxConnector(),
        catalogue=all_events,
        event_resolver=BookmakerEventResolver(
            identity, competition_resolver=module.resolve_competition if module else None),
        sports_gateway=sports_gateway,
        team_search=search,
    )


def _canonical_id(team_search: Callable[[str], dict | None], name: str) -> str | None:
    hit = team_search(name)
    return hit.get("canonical_id") if hit else None


def _find_event(
    events: Sequence[RawBookmakerEvent],
    team_search: Callable[[str], dict | None],
    home_id: str,
    away_id: str,
) -> RawBookmakerEvent | None:
    """Localise l'événement dont les deux slots résolvent vers {home_id, away_id}
    (égalité d'ENSEMBLE d'identités canoniques — jamais un match flou de chaînes)."""
    want = {home_id, away_id}
    for ev in events:
        s1 = _canonical_id(team_search, ev.slot_1_name)
        s2 = _canonical_id(team_search, ev.slot_2_name)
        if s1 and s2 and {s1, s2} == want:
            return ev
    return None


def decide_match(
    home_team: str,
    away_team: str,
    *,
    decision_time: datetime | None = None,
    sport: str = "football",
    connector=None,
    catalogue: Callable | None = None,
    event_resolver=None,
    sports_gateway=None,
    team_search: Callable[[str], dict | None] | None = None,
    evaluate: Callable = evaluate_live_event,
) -> MatchDecision:
    """Décision STRUCTURÉE pour un match (toutes sélections 1X2). Aucune math betting
    ici : délègue à `evaluate_live_event`. Défaut = catalogue Winamax live."""
    if decision_time is None:
        decision_time = datetime.now(timezone.utc)
    if connector is None:
        deps = _default_deps(sport)
        connector = connector or deps["connector"]
        catalogue = catalogue or deps["catalogue"]
        event_resolver = event_resolver or deps["event_resolver"]
        sports_gateway = sports_gateway or deps["sports_gateway"]
        team_search = team_search or deps["team_search"]

    home_id = _canonical_id(team_search, home_team)
    away_id = _canonical_id(team_search, away_team)
    if home_id is None or away_id is None:
        missing = home_team if home_id is None else away_team
        return MatchDecision(IDENTITY_UNRESOLVED,
                             f"identité non résolue : {missing} (aucun modèle sans identité)",
                             home_team, away_team)

    events = catalogue(connector, sport)
    raw_event = _find_event(events, team_search, home_id, away_id)
    if raw_event is None:
        return MatchDecision(EVENT_NOT_FOUND,
                             "aucun événement du catalogue ne correspond aux deux équipes",
                             home_team, away_team)

    result = evaluate(raw_event, decision_time=decision_time,
                      event_resolver=event_resolver, sports_gateway=sports_gateway)

    if result.status is not LiveEvaluationStatus.EVALUATED:
        status = _LIVE_STATUS_MAP.get(result.status, MODEL_UNAVAILABLE)
        return MatchDecision(status, result.reason, home_team, away_team,
                             competition=raw_event.competition, bookmaker=raw_event.bookmaker)

    selections = {
        d.selection: SelectionDecision(
            selection=d.selection, decision=d.decision, bookmaker_odds=d.bookmaker_odds,
            fair_probability=d.model_probability, probability_interval=d.probability_interval,
            expected_value=d.expected_value, worst_case_ev=d.worst_case_ev,
            no_vig_probability=d.no_vig_probability, edge=d.edge, reasons=tuple(d.reasons))
        for d in result.decisions
    }
    return MatchDecision(EVALUATED, "ok", home_team, away_team,
                         competition=raw_event.competition, bookmaker=raw_event.bookmaker,
                         selections=selections)


def decide_single(
    home_team: str,
    away_team: str,
    market: str,
    **kw,
) -> tuple[MatchDecision, SelectionDecision | None]:
    """Décision structurée pour UN marché. `(match, selection|None)`.

    Marché hors MATCH_WINNER -> `(MatchDecision(MARKET_UNAVAILABLE), None)` : aucun
    modèle structuré (jamais de moteur legacy pour over/under/BTTS)."""
    selection = _MARKET_TO_SELECTION.get(market.strip().lower())
    if selection is None:
        return MatchDecision(
            MARKET_UNAVAILABLE,
            f"marché '{market}' hors modèle structuré (seul MATCH_WINNER/1X2 est modélisé)",
            home_team, away_team), None

    match = decide_match(home_team, away_team, **kw)
    if not match.evaluated:
        return match, None
    return match, match.selections.get(selection)
