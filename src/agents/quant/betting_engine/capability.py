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

# États de capacité EN COUCHES (§5) — treillis dérivé, jamais déclaratif. Rend
# observable `catalogue ≠ data ≠ model ≠ SUPPORTED` : une compétition franchit les
# couches dans l'ordre et son état est la couche la plus profonde atteinte.
#   SPORT_UNAVAILABLE  : aucun module sportif           (ni modèle ni données)
#   MODEL_UNAVAILABLE  : module sportif mais aucun modèle pour les marchés découverts
#   DATA_UNAVAILABLE   : un modèle EXISTE mais l'identité/les données manquent
#                        (ex. MLS : le modèle football MATCH_WINNER s'appliquerait,
#                         mais aucune identité d'équipe ni historique ne résout)
#   EXPERIMENTAL/SUPPORTED : modèle + données présents, maturité MÉCANIQUE
# `DATA_UNAVAILABLE` est le point clé : ce n'est PAS un manque de modèle mais un
# manque de DONNÉES — la seule chose qui bloque l'extension à d'autres compétitions.
SPORT_UNAVAILABLE = "SPORT_UNAVAILABLE"
MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
DATA_UNAVAILABLE = "DATA_UNAVAILABLE"


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
    model_capable: bool                  # un modèle EXISTE pour >=1 marché (couche MODEL)
    data_capable: bool                   # identité/données résolvent (couche DATA)
    capability_state: str                # couche la plus profonde atteinte (treillis §5)
    maturity: str                        # UNAVAILABLE / EXPERIMENTAL / SUPPORTED
    evaluable: bool
    reason_unavailable: str | None       # None si évaluable

    # Alias rétro-compatible : `model_available` == existence d'un modèle (couche MODEL).
    @property
    def model_available(self) -> bool:
        return self.model_capable


def _competition_capability(sport, competition_name, raw_tid, events) -> CompetitionCapability:
    market_types = tuple(sorted({m.market_type.value for e in events for m in e.markets}))

    if sport not in SPORT_MODULES:
        # Couche 0 : pas même de module sportif -> ni modèle ni données.
        return CompetitionCapability(
            sport, competition_name, raw_tid, None, False, len(events), market_types,
            False, False, SPORT_UNAVAILABLE, "UNAVAILABLE", False, SPORT_NOT_SUPPORTED)

    canonical, status, _ = resolve_competition(raw_tid)
    resolved = status == "RESOLVED"                      # proxy couche DATA : identité résoluble

    # Marchés modélisés + maturité la plus avancée parmi eux.
    order = {"UNAVAILABLE": 0, "EXPERIMENTAL": 1, "SUPPORTED": 2}
    maturity = "UNAVAILABLE"
    model_capable = False
    for mt in market_types:
        available, mt_maturity = market_capability(sport, mt)
        if available:
            model_capable = True
            if order[mt_maturity] > order[maturity]:
                maturity = mt_maturity

    # Treillis en couches (l'ordre du reason est préservé pour la rétro-compat).
    if not model_capable:
        state, reason = MODEL_UNAVAILABLE, NO_MODEL_FOR_MARKET
    elif not resolved:
        # Le modèle existerait ; c'est la DONNÉE (identité/historique) qui manque.
        state, reason = DATA_UNAVAILABLE, COMPETITION_NOT_RESOLVED
    else:
        state, reason = maturity, None                   # EXPERIMENTAL / SUPPORTED
    return CompetitionCapability(
        sport, competition_name, raw_tid, canonical if resolved else None, resolved,
        len(events), market_types, model_capable, resolved, state, maturity,
        reason is None, reason)


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
    # Couches OBSERVABLES et DISTINCTES (§19) : catalogue ≠ data ≠ model ≠ SUPPORTED.
    competitions_model_capable: int      # un modèle existe (indépendant des données)
    competitions_data_capable: int       # identité/données résolvent
    competitions_evaluable: int          # modèle ET données (donc EXPERIMENTAL/SUPPORTED)
    events_evaluable: int
    by_reason: dict[str, int]            # raison de non-évaluabilité -> nb compétitions
    by_state: dict[str, int]             # état de capacité -> nb compétitions (treillis §5)
    capabilities: tuple[CompetitionCapability, ...]


def coverage_matrix(events, sport: str) -> CoverageMatrix:
    caps = capabilities_from_events(events, sport)
    evaluable = [c for c in caps if c.evaluable]
    by_reason = Counter(c.reason_unavailable for c in caps if not c.evaluable)
    by_state = Counter(c.capability_state for c in caps)
    return CoverageMatrix(
        sport=sport, competitions_discovered=len(caps),
        events_discovered=sum(c.discovered_events for c in caps),
        competitions_model_capable=sum(1 for c in caps if c.model_capable),
        competitions_data_capable=sum(1 for c in caps if c.data_capable),
        competitions_evaluable=len(evaluable),
        events_evaluable=sum(c.discovered_events for c in evaluable),
        by_reason=dict(by_reason), by_state=dict(by_state), capabilities=tuple(caps))
