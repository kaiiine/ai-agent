"""Découverte et complétion de l'historique sportif — sport-agnostique.

Une couche AU-DESSUS des briques existantes (providers, résolution d'identité,
appartenance saisonnière, walk-forward, registre de couverture), jamais une
seconde architecture : elle les orchestre à partir d'un MANQUE mesuré plutôt que
d'un catalogue de sources.

Le chemin complet : un besoin (`needs`) né d'une exclusion réelle (`gaps`), routé
vers des sources classées (`capability`, `classification`, `registry`), lues par
un adapter propre au format (`adapters/`), rapprochées sans lire aucun nom
(`identity_bridge`), filtrées contre la fuite temporelle (`leakage`),
dédoublonnées (`dedup`), tenues dans un sas auditable (`staging`), et classées
par ce qu'elles rapportent vraiment (`priority`).
"""

from .capability import CapabilityRegistry, HistoricalProviderCapability
from .classification import Axe, AxeMesure, SourceClassification
from .dedup import (DedupResult, DedupStatus, dedupliquer, tolerance_pour,
                    TOLERANCES_HEURES)
from .evidence import HistoricalMatchEvidence
from .gaps import agreger, besoins_par_entite, besoins_depuis_walk_forward
from .identity_bridge import AncrageTemporel, ancrer_par_instant
from .known_gaps import COUVERTURE_SUFFISANTE, besoins_mesures
from .leakage import (LeakageError, LeakVerdict, filtrer_admissibles,
                      verifier_admissibilite)
from .needs import HistoricalDataNeed
from .priority import (HistoricalBackfillPriority, PriorityBand, classer,
                       probabilite_de_recuperation)
from .registry import registre_par_defaut
from .staging import (BatchResult, JsonlStagingStore, StagedObservation,
                      StagingState, TransitionInterdite, transition_permise)

__all__ = [
    "AncrageTemporel", "Axe", "AxeMesure", "BatchResult", "COUVERTURE_SUFFISANTE",
    "CapabilityRegistry", "DedupResult", "DedupStatus",
    "HistoricalBackfillPriority", "HistoricalDataNeed", "HistoricalMatchEvidence",
    "HistoricalProviderCapability", "JsonlStagingStore", "LeakVerdict",
    "LeakageError", "PriorityBand", "SourceClassification", "StagedObservation",
    "StagingState", "TOLERANCES_HEURES", "TransitionInterdite", "agreger",
    "ancrer_par_instant", "besoins_depuis_walk_forward", "besoins_mesures",
    "besoins_par_entite", "classer", "dedupliquer", "filtrer_admissibles",
    "probabilite_de_recuperation", "registre_par_defaut", "tolerance_pour",
    "transition_permise", "verifier_admissibilite",
]
