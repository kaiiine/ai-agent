"""Registre des modules sportifs (§6.1) — dispatch sport -> (feature builder, modèle).

L'orchestrateur racine (`evaluate_live_event`, capability) dispatche via ce registre —
aucun `"football"` codé en dur ailleurs. Les SIX modèles validés hors échantillon y sont
enregistrés : c'est ce qui rend chaque sport RÉELLEMENT ATTEIGNABLE depuis le produit
standard (`axon recommend` -> scan Winamax -> resolver -> ici), et non seulement via des
seams de test. L'enregistrement donne la « model capability » (sport+marché) ; l'ÉVALUATION
d'un événement reste conditionnée à l'identité ET à la compétition résolues (couche DATA).

Import ordonné : `SportModule` est défini AVANT l'import des `*_MODULE` (les live_models
n'importent que `SportModule` d'ici) — pas de cycle.
"""

from __future__ import annotations

# SportModule vit dans un module SANS import (sport_module) pour casser le cycle
# registry <-> live_models. Ré-exporté ici pour rétro-compatibilité des imports existants.
from .sport_module import SportModule

__all__ = ["SportModule", "SPORT_MODULES"]


def _registry() -> dict[str, SportModule]:
    from .football.feature_engineering import build_event_feature_set
    from .football.market_models.one_x_two import OneXTwoModel
    from .basketball.live_model import BASKETBALL_MODULE
    from .baseball.live_model import BASEBALL_MODULE
    from .american_football.live_model import NFL_MODULE
    from .volleyball.live_model import VOLLEYBALL_MODULE
    from .hockey.live_model import HOCKEY_MODULE
    from .tennis.live_model import TENNIS_MODULE

    def _football_teams():
        from src.agents.quant.gateway.core.identity_data import TEAMS
        return list(TEAMS.values()) if isinstance(TEAMS, dict) else list(TEAMS)

    def _football_pricers():
        from .football.market_models.derived import FootballDerivedPricer
        return (FootballDerivedPricer(),)

    def _pricers_de_score(sport: str):
        """Les pricers de score d'un sport, s'il en a un de validé.

        Le baseball en déclare un aussi : sa configuration porte `law=None`, donc
        il s'abstient avec le motif du STOP statistique. Le brancher plutôt que
        l'omettre rend le refus VISIBLE dans l'entonnoir, au lieu de le confondre
        avec « ce sport n'intéresse personne ».
        """
        def _fabrique():
            from .score_pricer import ScorePricer
            return (ScorePricer(sport),)
        return _fabrique

    from dataclasses import replace as _replace

    return {
        "football": SportModule("football", build_event_feature_set, OneXTwoModel(),
                                entities=_football_teams,
                                market_pricers=_football_pricers),
        "basketball": _replace(BASKETBALL_MODULE,
                               market_pricers=_pricers_de_score("basketball")),
        "baseball": _replace(BASEBALL_MODULE,
                             market_pricers=_pricers_de_score("baseball")),
        "american_football": _replace(NFL_MODULE,
                                      market_pricers=_pricers_de_score("american_football")),
        "volleyball": VOLLEYBALL_MODULE,
        "hockey": HOCKEY_MODULE,
        "tennis": TENNIS_MODULE,
    }


SPORT_MODULES: dict[str, SportModule] = _registry()


def resolve_competition_any_sport(event):
    """Résout la compétition d'un événement SELON SON SPORT.

    Les sports de ligue résolvent par identifiant de tournoi bookmaker : la table
    est stable. Le tennis ne le peut pas — un `raw_tournament_id` y désigne une
    ÉDITION (176503 = Montréal 2026), pas une compétition — et résout donc par
    recouvrement de plateau. `SportModule.resolve_competition` porte cette
    différence ; à défaut, on retombe sur la table.

    Cette fonction existe parce que le résolveur était construit à DEUX endroits :
    le chemin unitaire injectait celui du sport demandé, le batch prenait le défaut
    par omission. Même événement, deux verdicts — `competition:tennis:atp:tour`
    d'un côté, `None` de l'autre, et zéro évaluation en batch. Un batch mélange les
    sports par nature : le dispatch doit se faire par ÉVÉNEMENT, jamais par appel.
    """
    from ..bookmakers.bookmaker_registry import _default_resolve_competition

    module = SPORT_MODULES.get(event.sport)
    if module is not None and module.resolve_competition is not None:
        return module.resolve_competition(event)
    return _default_resolve_competition(event.raw_tournament_id)


def build_event_resolver():
    """L'UNIQUE fabrique de `BookmakerEventResolver` du produit.

    `BookmakerEventResolver` prend DEUX dépendances injectables — le référentiel
    d'identités et le résolveur de compétition — et chacune a un défaut
    football-only. Quatre sites le construisaient à la main ; deux oubliaient le
    résolveur de compétition, et le même événement recevait deux verdicts selon
    le chemin d'appel (`competition:tennis:atp:tour` ici, `None` là-bas, zéro
    évaluation en batch).

    Un défaut silencieux ne se remarque pas à la lecture : il faut se souvenir de
    le passer. Une fabrique, elle, ne s'oublie pas — elle se voit dans le diff du
    jour où quelqu'un construit un cinquième résolveur.
    """
    from src.agents.quant.gateway.core.identity_resolver import IdentityResolver
    from ..bookmakers.bookmaker_registry import BookmakerEventResolver

    return BookmakerEventResolver(
        IdentityResolver(all_known_entities()),
        competition_resolver=resolve_competition_any_sport)


def all_known_entities() -> list:
    """Union des entités des SEPT sports, pour un résolveur unique.

    Sûr malgré le mélange : `BookmakerEventResolver._name_matches` filtre par
    préfixe d'identifiant (`team:football:`, `player:tennis:`), donc un joueur de
    tennis ne peut pas matcher un club de football même à nom identique.

    Sans cette union, tout consommateur devait construire son résolveur à partir
    d'un seul référentiel — et prenait invariablement celui du football, rendant
    les six autres sports inertes derrière une façade générique.
    """
    return [e for module in SPORT_MODULES.values() for e in module.known_entities()]
