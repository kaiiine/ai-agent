"""Model Capability Registry (§4) — source de vérité DÉRIVÉE (jamais un registre
concurrent) : pour un `(sport, competition, market_type)`, existe-t-il un modèle et
quel est son état (`UNAVAILABLE` / `EXPERIMENTAL` / `SUPPORTED`) ?

S'appuie sur l'existant : `sports.registry.SPORT_MODULES` (quels sports/marchés ont
un modèle), `support_status.resolve_market_status` (maturité mécanique), et le mapping
de compétitions Winamax (`resolve_competition`) pour savoir si la compétition est
canonicalisable. Aucune spécificité `if league == …` : la connaissance vit dans les
modules/mappings, pas dans le chemin principal.

`catalogue coverage ≠ model coverage` : une compétition découverte n'est ÉVALUABLE que
si (a) le sport a un module, (b) le marché a un modèle, (c) la compétition résout vers
une identité canonique. Sinon elle est ISOLÉE avec une raison typée — jamais évaluée
en silence, jamais arrêtant le run.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .bookmakers.winamax.competition_mapping import resolve_competition
from .sports.registry import SPORT_MODULES
from .support_status import resolve_market_status

# Raisons stables de non-évaluabilité (machine-readable).
SPORT_NOT_SUPPORTED = "SPORT_NOT_SUPPORTED"
COMPETITION_NOT_RESOLVED = "COMPETITION_NOT_RESOLVED"
NO_MODEL_FOR_MARKET = "NO_MODEL_FOR_MARKET"


def market_capability(sport: str, market_type: str) -> tuple[bool, str]:
    """(model_available, maturity) pour un `(sport, market_type)`. Maturité DÉRIVÉE
    du ledger de support (jamais déclarative) ; UNAVAILABLE si aucun modèle."""
    module = SPORT_MODULES.get(sport)
    if module is None:
        return False, "UNAVAILABLE"
    model = module.model
    if getattr(model, "market_type", None) != market_type:
        return False, "UNAVAILABLE"
    maturity = resolve_market_status(model.model_name, model.model_version)
    return True, maturity.value


@dataclass(frozen=True)
class CompetitionCapability:
    sport: str
    competition_name: str                # nom Winamax
    raw_tournament_id: str | None
    canonical_competition: str | None    # identité canonique si résolue
    competition_resolved: bool
    discovered_events: int
    market_types: tuple[str, ...]        # marchés découverts
    model_available: bool
    maturity: str                        # UNAVAILABLE / EXPERIMENTAL / SUPPORTED
    evaluable: bool
    reason_unavailable: str | None       # None si évaluable


def _competition_capability(sport, competition_name, raw_tid, events) -> CompetitionCapability:
    market_types = tuple(sorted({m.market_type.value for e in events for m in e.markets}))

    if sport not in SPORT_MODULES:
        return CompetitionCapability(
            sport, competition_name, raw_tid, None, False, len(events), market_types,
            False, "UNAVAILABLE", False, SPORT_NOT_SUPPORTED)

    canonical, status, _ = resolve_competition(raw_tid)
    resolved = status == "RESOLVED"

    # Marchés modélisés + maturité la plus avancée parmi eux.
    order = {"UNAVAILABLE": 0, "EXPERIMENTAL": 1, "SUPPORTED": 2}
    maturity = "UNAVAILABLE"
    model_available = False
    for mt in market_types:
        available, mt_maturity = market_capability(sport, mt)
        if available:
            model_available = True
            if order[mt_maturity] > order[maturity]:
                maturity = mt_maturity

    if not model_available:
        reason = NO_MODEL_FOR_MARKET
    elif not resolved:
        reason = COMPETITION_NOT_RESOLVED
    else:
        reason = None
    return CompetitionCapability(
        sport, competition_name, raw_tid, canonical if resolved else None, resolved,
        len(events), market_types, model_available, maturity, reason is None, reason)


def capabilities_from_events(events, sport: str) -> list[CompetitionCapability]:
    """Regroupe les événements scannés par compétition et calcule la capacité de
    chacune. Découverte complète : aucune compétition n'est écartée."""
    by_comp: dict[tuple, list] = {}
    for event in events:
        key = (event.competition or "(compétition inconnue)", event.raw_tournament_id)
        by_comp.setdefault(key, []).append(event)
    caps = [_competition_capability(sport, name, tid, evs) for (name, tid), evs in by_comp.items()]
    return sorted(caps, key=lambda c: (not c.evaluable, -c.discovered_events, c.competition_name))


@dataclass(frozen=True)
class CoverageMatrix:
    sport: str
    competitions_discovered: int
    events_discovered: int
    competitions_evaluable: int
    events_evaluable: int
    by_reason: dict[str, int]            # raison de non-évaluabilité -> nb compétitions
    capabilities: tuple[CompetitionCapability, ...]


def coverage_matrix(events, sport: str) -> CoverageMatrix:
    caps = capabilities_from_events(events, sport)
    evaluable = [c for c in caps if c.evaluable]
    by_reason = Counter(c.reason_unavailable for c in caps if not c.evaluable)
    return CoverageMatrix(
        sport=sport, competitions_discovered=len(caps),
        events_discovered=sum(c.discovered_events for c in caps),
        competitions_evaluable=len(evaluable),
        events_evaluable=sum(c.discovered_events for c in evaluable),
        by_reason=dict(by_reason), capabilities=tuple(caps))
