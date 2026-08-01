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
    return {
        "football": SportModule("football", build_event_feature_set, OneXTwoModel()),
        "basketball": BASKETBALL_MODULE,
        "baseball": BASEBALL_MODULE,
        "american_football": NFL_MODULE,
        "volleyball": VOLLEYBALL_MODULE,
        "hockey": HOCKEY_MODULE,
    }


SPORT_MODULES: dict[str, SportModule] = _registry()
